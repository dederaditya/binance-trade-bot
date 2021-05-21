import logging.handlers
import subprocess

from .notifications import NotificationHandler
from .config import Config

class Logger:
    logger = None

    def __init__(self, config, logging_service="crypto_trading", enable_notifications=True):
        self.logger = logging.getLogger(f"{logging_service}_logger")
        self.logger.setLevel(logging.DEBUG)

        stdout_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        stdout_handler = logging.StreamHandler()
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(stdout_formatter)
        self.logger.addHandler(stdout_handler)

        if enable_notifications:
            try:
                notification_formatter = logging.Formatter(
                    f"```\n<{config.NOTIFICATION_NAME}>: %(name)s - %(levelname)s - %(message)s\n```")
                notification_handler = NotificationHandler()
                notification_handler.setLevel(logging.INFO)
                notification_handler.setFormatter(notification_formatter)
                self.logger.addHandler(notification_handler)
            except Exception as e:
                self.warning(f"Couldn't enable notifications: {e}")

    def log(self, message, level):
        self.logger.log(level, message)

    def info(self, message):
        self.log(message, logging.INFO)

    def warning(self, message):
        self.log(message, logging.WARNING)

    def error(self, message):
        self.log(message, logging.ERROR)

    def debug(self, message):
        self.log(message, logging.DEBUG)

    def log_progress(self):
        with subprocess.Popen(["./scripts/checkProgress.sh", "LIMIT 10"], stdout=subprocess.PIPE) as session:
            progress = session.stdout.read().decode("UTF-8")
            message = f"Progress report for up to the last 10 trades:\n{progress}"
            self.info(message)
