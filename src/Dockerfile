# 使用官方 Python 3 基础镜像
FROM python:3.8-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
#RUN apt-get update && apt-get install -y build-essential
RUN apt-get update && apt-get install -y tzdata

# 设置环境变量
ENV PICA_SECRET_KEY="" \
    REQUEST_PROXY="" \
    PACKAGE_TYPE="False" \
    BARK_URL="" \
    INTERVAL_TIME="5" \
    DETAIL="False" \
    REQUEST_TIME_OUT="10" \
    CHANGE_FAVOURITE="False" \
    DELETE_COMIC="True" \
    TZ="Asia/Shanghai"

# 将当前目录内容复制到工作目录中
COPY . /app

# 安装依赖项
RUN pip install --no-cache-dir requests urllib3 pytz

# 指定容器启动时执行的命令
CMD ["python", "main.py"]
