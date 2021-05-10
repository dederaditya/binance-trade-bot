import logging
import os
import queue
import threading

import apprise


APPRISE_CONFIG_PATH = "./config/apprise.yml"


class NotificationHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

        self.worker = NotificationWorker()
        self.worker.start_worker()

    def emit(self, record):
        self.worker.send_notification(self.format(record))


class NotificationWorker:
    def __init__(self):
        if not os.path.exists(APPRISE_CONFIG_PATH):
            raise RuntimeError("No Apprise config found.")

        config = apprise.AppriseConfig()
        config.add(APPRISE_CONFIG_PATH)
        self.apobj = apprise.Apprise()
        self.apobj.add(config)

        self.queue = queue.Queue()

    def start_worker(self):
        threading.Thread(target=self.process_queue, daemon=True).start()

    def process_queue(self):
        while True:
            message, attachments = self.queue.get()

            if attachments:
                self.apobj.notify(body=message, attach=attachments)
            else:
                self.apobj.notify(body=message)

            self.queue.task_done()

    def send_notification(self, message, attachments=None):
        self.queue.put((message, attachments or []))
