# save this as app.py
from downloader import handle_download
import redis
from rq import Queue
import rq_dashboard
from flask import Flask, render_template, request, redirect
from os import environ
app = Flask(__name__)
TIMEOUT_IN_DAYS = 4
TIMEOUT = 60 * 60 * 24 * TIMEOUT_IN_DAYS
# https://python-rq.org/docs/results/#dealing-with-job-timeouts
REDIS = redis.Redis(host=environ["REDIS_HOSTNAME"], port=6379, db=0)
QUEUE = Queue(environ["QUEUE_NAME"], default_timeout=TIMEOUT, connection=REDIS)  # no args implies the default queue

app.config.from_object(rq_dashboard.default_settings)
app.config["RQ_DASHBOARD_REDIS_URL"] = f"redis://{environ["REDIS_HOSTNAME"]}:6379"
rq_dashboard.web.setup_rq_connection(app)
app.register_blueprint(rq_dashboard.blueprint, url_prefix="/rq")

@app.route("/", methods=['GET', 'POST'])
def hello():
    global DOWNLOADS
    if request.method == "POST":
        if 'target_url' not in request.form:
            return 'No url provided...', 400
        target_url = request.form['target_url']
        content_mask = request.form['content_mask']
        app.logger.debug("target_url=%s, content_mask=%s, path=%s", target_url, content_mask, environ.get("YT_DOWNLOADER_PATH"))
        QUEUE.enqueue(handle_download, target_url, content_mask)
        return redirect("/")
    
    return render_template('index.html')



def runApp():
    should_be_debug = environ["DEBUG"]
    host = "0.0.0.0"
    port = 5000
    app.logger.info(f"{bool(should_be_debug)}")
    if(bool(should_be_debug) is True):
        app.run(host=host, debug=True, port=port)
    else:
        from waitress import serve
        serve(app, host=host, port=port)
if __name__ == "__main__":
    try:
        runApp()
    except KeyboardInterrupt:
        exit(0)
    
