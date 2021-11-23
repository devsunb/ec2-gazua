# -*- coding: utf-8 -*-

from os import path

import yaml

from ec2gazua.utils import read


class Config(object):
    _items = {}

    def __init__(self, config_path):
        self.config_path = config_path
        self._valid_config_file()
        self._load()

    def _valid_config_file(self):
        if not path.exists(self.config_path):
            raise IOError("Config file not exists: %s" % self.config_path)

        if not path.isfile(self.config_path):
            raise IOError(
                ".ec2-gz must be a file. not directory: %s" % self.config_path)

    def _load(self):
        content = self._read()
        configs = {}
        for data in yaml.safe_load_all(content):
            if data['name'] in configs:
                raise ValueError('%s is duplicated name in config' % data['name'])
            configs[data['name']] = data
        self._items = configs

    def items(self):
        return self._items.items()

    def _read(self):
        return read(self.config_path)

    def __getitem__(self, aws_name):
        return self._items[aws_name]
