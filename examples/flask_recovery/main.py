from flask import Flask

app = Flask(__name__)


@app.get("/")
def home():
    return "First Run recovered the right entry point"
