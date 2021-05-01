from __future__ import with_statement

import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

import requests
from django.db import connection
from django.db import connections
from django.utils.functional import wraps
from requests.exceptions import RequestException


def get_free_tcp_port():
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("", 0))
    addr, port = tcp.getsockname()
    tcp.close()
    return port


class KolibriServer(object):
    def __init__(
        self,
        autostart=True,
        settings="kolibri.deployment.default.settings.base",
        db_name="default",
    ):
        self.env = os.environ.copy()
        self.env["KOLIBRI_HOME"] = tempfile.mkdtemp()
        self.env["DJANGO_SETTINGS_MODULE"] = settings
        self.env["POSTGRES_DB"] = db_name
        self.env["KOLIBRI_ZIP_CONTENT_PORT"] = str(get_free_tcp_port())
        self.db_path = os.path.join(self.env["KOLIBRI_HOME"], "db.sqlite3")
        self.db_alias = uuid.uuid4().hex
        self.port = get_free_tcp_port()
        self.baseurl = "http://127.0.0.1:{}/".format(self.port)
        if autostart:
            self.start()

    def start(self):
        self._instance = subprocess.Popen(
            ["kolibri", "start", "--port", str(self.port), "--foreground"],
            env=self.env,
        )
        self._wait_for_server_start()

    def manage(self, *args):
        subprocess.call(
            ["kolibri", "manage"] + list(args),
            env=self.env,
        )

    def create_model(self, model, **kwargs):
        kwarg_text = ",".join(
            '{key}=\\"{value}\\"'.format(key=key, value=value)
            for key, value in kwargs.items()
        )
        self.pipe_shell(
            "from {module_path} import {model_name}; {model_name}.objects.create({})".format(
                kwarg_text, module_path=model.__module__, model_name=model.__name__
            )
        )

    def delete_model(self, model, **kwargs):
        kwarg_text = ",".join(
            '{key}=\\"{value}\\"'.format(key=key, value=value)
            for key, value in kwargs.items()
        )
        self.pipe_shell(
            "from {module_path} import {model_name}; obj = {model_name}.objects.get({}); obj.delete()".format(
                kwarg_text, module_path=model.__module__, model_name=model.__name__
            )
        )

    def pipe_shell(self, text):
        subprocess.call(
            'echo "{}" | kolibri shell'.format(text), env=self.env, shell=True
        )

    def _wait_for_server_start(self, timeout=20):
        for i in range(timeout * 2):
            try:
                resp = requests.get(self.baseurl, timeout=3)
                if resp.status_code > 0:
                    return
            except RequestException:
                pass
            time.sleep(0.5)

        raise Exception("Server did not start within {} seconds".format(timeout))

    def kill(self):
        try:
            subprocess.call("kolibri stop", env=self.env, shell=True)
            self._instance.kill()
            shutil.rmtree(self.env["KOLIBRI_HOME"])
        except OSError:
            pass


class multiple_kolibri_servers(object):
    def __init__(self, count=2):
        self.server_count = count

    def __enter__(self):

        # spin up the servers
        if "sqlite" in connection.vendor:

            self.servers = [KolibriServer() for i in range(self.server_count)]

            # calculate the DATABASE settings
            connections.databases = {
                server.db_alias: {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": server.db_path,
                    "OPTIONS": {"timeout": 100},
                }
                for server in self.servers
            }

        if "postgresql" in connection.vendor:

            if self.server_count == 3:
                self.servers = [
                    KolibriServer(
                        settings="kolibri.deployment.default.settings.postgres_test",
                        db_name="eco_test" + str(i + 1),
                    )
                    for i in range(self.server_count)
                ]

            if self.server_count == 5:
                self.servers = [
                    KolibriServer(
                        settings="kolibri.deployment.default.settings.postgres_test",
                        db_name="eco2_test" + str(i + 1),
                    )
                    for i in range(self.server_count)
                ]

            # calculate the DATABASE settings
            connections.databases = {
                server.db_alias: {
                    "ENGINE": "django.db.backends.postgresql",
                    "USER": "postgres",
                    "NAME": server.env["POSTGRES_DB"],
                }
                for server in self.servers
            }

        return self.servers

    def __exit__(self, typ, val, traceback):

        # make sure all the servers are shut down
        for server in self.servers:
            server.kill()

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):

            assert "servers" not in kwargs

            with self as servers:
                kwargs["servers"] = servers
                return f(*args, **kwargs)

        return wrapper
