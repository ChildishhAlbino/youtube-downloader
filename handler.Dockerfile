FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY templates ./templates
COPY *.py ./

CMD [ "python", "./handler.py" ] 

EXPOSE 5000