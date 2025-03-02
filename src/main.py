# encoding: utf-8
# version 1.1
import io
import json
import sys
import time
import shutil
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from client import Pica
from utils import *


# 配置日志
log_folder = './logs'
os.makedirs(log_folder, exist_ok=True)
log_formatter = TimezoneFormatter(
    fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S', timezone="Asia/Shanghai"
)
#log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')


# 自定义生成日志文件名的函数
def get_log_filename(name):
    return os.path.join(log_folder, f'{name}.log')

def build_log_handler(
        when='midnight', 
        interval=1, 
        backup_count=int(get_cfg('param', 'backup_count'))
    ):
    # create a new TimedRotatingFileHandler
    log_handler = TimedRotatingFileHandler(
        get_log_filename('runing'),
        when=when,                # 轮转时间
        interval=interval,        # 轮转周期
        backupCount=backup_count  # 保留最近日志文件最大天数
    )
    log_handler.suffix = "%Y-%m-%d"
    log_handler.setLevel(logging.INFO)
    log_handler.setFormatter(log_formatter)
    log_handler.addFilter(InfoWarningFilter())
    return log_handler

def build_error_log_handler(
        when='midnight',
        interval=1,
        backup_count=int(get_cfg('param', 'backup_count'))
    ):
    # create a new ERROR TimedRotatingFileHandler, only logs ERROR level and above! 
    error_log_handler = TimedRotatingFileHandler(
        get_log_filename('ERROR'),
        when=when,                # 每天轮转一次
        interval=interval,        # 轮转周期为1天
        backupCount=backup_count  # 保留最近?天的日志文件
    )
    error_log_handler.suffix = "%Y-%m-%d"
    error_log_handler.setLevel(logging.ERROR)  # 只记录 ERROR 级别及以上的日志
    error_log_handler.setFormatter(log_formatter)
    return error_log_handler


# only_latest: true增量下载    false全量下载
def download_comic(pica_server, comic, db_path, is_favo):
    cid        = comic.get("_id")
    title      = comic.get("title")
    author     = comic.get("author", 'Unknown')
    author     = 'Unknown' if author == '' else author
    categories = comic.get("categories")
    episodes   = pica_server.episodes_all(cid, title)
    num_pages  = comic.get("pagesCount", -1)
    comic_name = (
        f"[{convert_file_name(title)}]"
        f"[{convert_file_name(author)}]"
        #f"[{convert_file_name(categories)}]"
    )
    comic_name = ensure_valid_relativePath(comic_name, max_length=255)
    comic_path = Path(
        os.path.join(
            ".",
            "comics",
            f"{convert_file_name(author)}",
            comic_name
        )
    )

    if is_favo:
        # 过滤已下载漫画章节
        episodes = filter_comics_downloaded(comic, episodes, db_path)
    else:
        # 按规则过滤漫画并过滤已下载漫画章节
        episodes = filter_comics_rule(comic, episodes, db_path)
        episodes = filter_comics_downloaded(comic, episodes, db_path)

    if episodes:
        print(
            'downloading:[%s]-[%s]-[%s]-[is_favo:%s]-[total_pages:%d]' % 
            (title, author, categories, is_favo, num_pages), 
            flush=True
        )
    else:
        return comic_path

    # 记录已扫描过的id
    mark_comic_as_downloaded(cid, db_path)
    # 登记漫画信息为json文件
    comic_path.mkdir(parents=True, exist_ok=True)
    record_comic_data(comic, comic_path)
    
    is_detail  = os.environ.get("DETAIL", "False") == "True"
    for episode in episodes:
        chapter_title = convert_file_name(episode["title"])
        chapter_title = ensure_valid_relativePath(chapter_title, max_length=255)
        chapter_path  = os.path.join(comic_path, chapter_title)
        chapter_path  = Path(chapter_path)
        chapter_path.mkdir(parents=True, exist_ok=True)

        image_urls = []
        current_page = 1
        # 扫描章节
        while True:
            page_data = json.loads(
                pica_server.picture(cid, episode["order"], current_page).content
            )["data"]["pages"]["docs"]
            current_page += 1
            if page_data:
                image_urls.extend(list(map(
                    lambda i: i['media']['fileServer'] + '/static/' + i['media']['path'], 
                    page_data
                )))
            else:
                break
        if not image_urls:
            logging.error(f"No images found of episode:'{chapter_title}' in comic:'{title}'.")
            continue
        
        # 下载章节
        concurrency      = int(get_cfg('crawl', 'concurrency'))
        image_urls_parts = list_partition(image_urls, concurrency)
        downloaded_count = 0.
        for image_urls_part in image_urls_parts:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {
                    executor.submit(
                        download, 
                        pica_server, 
                        chapter_path, 
                        image_urls.index(image_url), 
                        image_url, 
                    ): image_url 
                    for image_url in image_urls_part
                }
                for future in as_completed(futures):
                    image_url = futures[future]
                    try:
                        future.result()
                        downloaded_count += 1
                    except Exception as e:
                        current_image = image_urls.index(image_url) + 1
                        episode_title = episode["title"]
                        logging.error(
                            f"Fail to download the {current_image}-th image "
                            f"in episode:{episode_title} "
                            f"in comic:{title} with "
                            f"Exception:'{e}'"
                        )
                        continue

            if is_detail:
                episode_title = episode["title"]
                print(
                    f"[episode:{episode_title:<10}] "
                    f"downloaded:{downloaded_count:>6}, "
                    f"total:{len(image_urls):>4}, "
                    f"progress:{int(downloaded_count / len(image_urls) * 100):>3}%", 
                    flush=True
                )
        if downloaded_count == len(image_urls):
            update_downloaded_episodes(cid, episode["title"], db_path)
        else:
            episode_title = episode["title"]
            logging.error(
                f"Failed to download the episodes:{episode_title} "
                f"of comic:{title}. "
                f"Currently, {downloaded_count} images(total_images:{len(image_urls)}) "
                "from this episode have been downloaded."
            )

    # 下载每本漫画的间隔时间
    if os.environ.get("INTERVAL_TIME"):
        time.sleep(int(os.environ.get("INTERVAL_TIME")))
    return comic_path


def main(isTest=False):
    log_handler = build_log_handler()
    error_log_handler = build_error_log_handler()
    logging.basicConfig(
        level=logging.INFO,
        handlers=[log_handler, error_log_handler]
    )

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf8')
    sys.stdout = LoggerRedirect(sys.stdout)

    # 登录并打卡
    pica_server = Pica()
    pica_server.login()
    pica_server.punch_in()

    # 数据库
    db_path = os.path.join('.', 'data', 'downloaded.db')
    init_db(db_path)

    # 排行榜的漫画
    ranked_comics = pica_server.leaderboard()
    print('排行榜共计%d本漫画' % (len(ranked_comics)), flush=True)

    # 关键词订阅漫画
    searched_comics = []
    keywords = get_cfg('param', 'subscribe_keyword').split(',')
    for keyword in keywords:
        searched_comics_ = pica_server.search_all(keyword)
        print('关键词%s: 检索到%d本漫画' % (keyword, len(searched_comics_)), flush=True)
        searched_comics += searched_comics_

    # 收藏夹漫画
    favourited_comics = pica_server.my_favourite_all()
    print('已下载共计%d本漫画' % get_downloaded_comic_count(db_path), flush=True)
    print('收藏夹共计%d本漫画' % (len(favourited_comics)),            flush=True)
    isChangeFavo = os.environ.get("CHANGE_FAVOURITE", False) == "True"

    if isTest:
        num_comics = 2
    else:  
        num_comics = len(ranked_comics) + len(searched_comics) + len(favourited_comics)
    for comic in (ranked_comics + favourited_comics + searched_comics)[:num_comics]:
        try:
            # 收藏夹:全量下载  其余:增量下载
            comic_path = download_comic(pica_server, comic, db_path, comic in favourited_comics)
            info       = pica_server.comic_info(comic['_id'])
            # 收藏夹中的漫画被下载后,自动取消收藏,避免下次运行时重复下载
            if info["data"]['comic']['isFavourite'] and isChangeFavo:
                pica_server.favourite(comic["_id"])
            update_comic_data(comic, db_path)
            
        except Exception as e:
            comic_title = comic["title"]
            logging.error(
                f"Download failed for comic:'{comic_title}', with Exception:{e}"
            )
            continue


    # 打包成zip文件, 并删除旧数据 , 删除comics文件夹会导致docker挂载报错
    if os.environ.get("PACKAGE_TYPE", "False") == "True":
        print("The comic is being packaged")
        for folderName in os.listdir('./comics'):
            folder_path = os.path.join('./comics', folderName)
            if os.path.isdir(folder_path):
                output_path = os.path.join('./output', folderName)
                for chapter_folder in os.listdir(folder_path):
                    chapter_path = os.path.join(folder_path, chapter_folder)
                    output_path  = os.path.join('./output', folderName, chapter_folder)
                    if os.path.isdir(chapter_path):
                        os.makedirs(output_path, exist_ok=True)
                        zip_subfolders(chapter_path, output_path)
                        # 记录漫画信息
                        if 'comic.json' in os.listdir(chapter_path):
                            json_path = os.path.join(chapter_path, 'comic.json')
                            target_json_path = os.path.join(output_path, 'comic.json')
                            shutil.copy(json_path, target_json_path)

        if os.environ.get("DELETE_COMIC", "True") == "True":
            # delete folders in comics
            print("The comics are being deleted")
            for fileName in os.listdir('./comics'):
                file_path = os.path.join('./comics', fileName)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        
        else:
            # move comics to backup folders
            print("The comics are being moved")
            target_path = os.path.join('./comics_origin_backUp')
            os.makedirs(target_path, exist_ok=True)
            file_path = './comics'
            move_incremental(file_path, target_path)


    # 发送消息通知
    if os.environ.get("BARK_URL"):
        requests.get(
            os.environ.get("BARK_URL") + " " +
            f"排行榜漫画共计{len(ranked_comics)}" +
            f"关键词漫画共计{len(searched_comics)}" +
            f"收藏夹漫画共计{len(favourited_comics)}"
        )
    print("RUN COMPLETED!")
    return True


if __name__ == '__main__':
    main()
