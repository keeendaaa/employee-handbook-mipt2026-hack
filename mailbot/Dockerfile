FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py navigator_client.py reply_format.py panel.html ./mailbot/
USER 10001:10001
ENTRYPOINT ["python", "-m", "mailbot.app"]
