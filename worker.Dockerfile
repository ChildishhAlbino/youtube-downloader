FROM python:3

WORKDIR /usr/src/app
COPY requirements.txt ./
COPY bin ./bin
RUN pip install setuptools
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get -y update
RUN apt-get -y upgrade
RUN apt-get install -y ffmpeg

COPY templates ./templates
COPY *.py ./

CMD [ "python", "./worker.py" ]