# -*- coding: utf-8 -*-
import argparse
import logging

from ec2gazua import gazua

logger = logging.getLogger('GAZUA')


def main():
    option = get_option()
    setup_logger(option.log_level)
    gazua.run(option.config)


def get_option():
    parser = argparse.ArgumentParser(description='ECS EC2 Gazua')
    parser.add_argument('-c', '--config', type=str, default='.ec2-gz', help='Config file path')
    parser.add_argument('-l', '--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help='Logging level')
    return parser.parse_args()


def setup_logger(log_level):
    logger.setLevel(log_level.upper())
    formatter = logging.Formatter('%(asctime)s %(processName)s [%(levelname)s] (%(filename)s:%(lineno)d) %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


if __name__ == '__main__':
    main()
