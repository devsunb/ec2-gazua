# -*- coding: utf-8 -*-
import logging
from collections import OrderedDict
from os.path import expanduser
from os.path import isfile

import boto3

from ec2gazua.config import Config
from ec2gazua.logger import log

logger = logging.getLogger('GAZUA')


class EC2InstanceManager(object):
    instances = {}

    def add_instance(self, aws_name, instance):
        if aws_name not in self.instances:
            self.instances[aws_name] = {}
        for cluster in instance.clusters:
            if cluster not in self.instances[aws_name]:
                self.instances[aws_name][cluster] = {}
            for task_definition in instance.task_definitions:
                if task_definition not in self.instances[aws_name][cluster]:
                    self.instances[aws_name][cluster][task_definition] = []
                self.instances[aws_name][cluster][task_definition].append(instance)

    @property
    def aws_names(self):
        return self.instances.keys()

    def sort(self):
        sorted_instances = OrderedDict()
        for aws_name, clusters in OrderedDict(sorted(self.instances.items(), key=lambda x: x[0])).items():
            sorted_instances[aws_name] = {}
            for cluster, task_definitions in OrderedDict(sorted(clusters.items(), key=lambda x: x[0])).items():
                sorted_instances[aws_name][cluster] = {}
                for task_definition, instances in OrderedDict(
                        sorted(task_definitions.items(), key=lambda x: x[0])).items():
                    instances.sort(key=lambda x: x.name)
                    sorted_instances[aws_name][cluster][task_definition] = instances
        self.instances = sorted_instances


class EC2InstanceLoader(object):
    def __init__(self, config_path):
        self.config = Config(config_path)

    @staticmethod
    def _request_cluster_arns(client):
        return client.list_clusters()['clusterArns']

    @staticmethod
    def _request_cluster_names(client, cluster_arns):
        return {
            x['clusterArn']: x['clusterName']
            for x in client.describe_clusters(clusters=cluster_arns)['clusters']
        }

    def _request_container_instance_ids(self, client, clusters):
        container_instance_id_map = {}
        for cluster in clusters:
            container_instances = client.list_container_instances(cluster=cluster)['containerInstanceArns']
            if container_instances:
                container_instance_describes = client.describe_container_instances(
                    cluster=cluster, containerInstances=container_instances)['containerInstances']
                for c in container_instance_describes:
                    container_instance_id_map[c['containerInstanceArn']] = c['ec2InstanceId']
        return container_instance_id_map

    @staticmethod
    def _request_task_definitions(client):
        task_definition_family_map = {}
        for x in client.list_task_definition_families(status='ACTIVE')['families']:
            task_definition = client.describe_task_definition(taskDefinition=x)['taskDefinition']
            logger.debug(f'read task definition: {task_definition["family"]}')
            task_definition_family_map[task_definition['taskDefinitionArn']] = task_definition['family']
        return task_definition_family_map

    @staticmethod
    def _request_tasks(client, clusters):
        tasks = []
        for c in clusters:
            task_arns = client.list_tasks(cluster=c)['taskArns']
            task_describes = client.describe_tasks(cluster=c, tasks=task_arns)['tasks'] if task_arns else []
            tasks += [t for t in task_describes if 'containerInstanceArn' in t]
        return tasks

    @staticmethod
    def _request_instances(client, instance_ids):
        return [y for x in client.describe_instances(InstanceIds=instance_ids)['Reservations'] for y in x['Instances']]

    def load_all(self):
        manager = EC2InstanceManager()
        logger.info('ECS EC2 Gazua~!!')
        for aws_name, item in self.config.items():
            logger.info(f'Instance loading: {aws_name}')
            credential = self.config[aws_name]['credential']
            session = boto3.Session(
                aws_access_key_id=credential['aws_access_key_id'],
                aws_secret_access_key=credential['aws_secret_access_key'],
                region_name=credential['region'])
            ec2_client = session.client('ec2')
            ecs_client = session.client('ecs')
            logger.debug('boto3 session, client created')
            cluster_arns = self._request_cluster_arns(ecs_client)
            logger.debug('read cluster list')
            cluster_names = self._request_cluster_names(ecs_client, cluster_arns)
            logger.debug('read cluster names')
            ci_ids = self._request_container_instance_ids(ecs_client, cluster_arns)
            logger.debug('read container instance ids')
            tds = self._request_task_definitions(ecs_client)
            logger.debug('read task definitions')

            def get_td(arn):
                return tds[arn] if arn in tds else 'UNKNOWN'

            tasks = self._request_tasks(ecs_client, cluster_arns)
            logger.debug('read tasks')
            instance_ids = list(set([ci_ids[t['containerInstanceArn']] for t in tasks]))
            instances = self._request_instances(ec2_client, instance_ids)
            logger.debug('read instances')
            id_cluster_map = {}
            id_td_map = {}
            for t in tasks:
                if ci_ids[t['containerInstanceArn']] not in id_cluster_map:
                    id_cluster_map[ci_ids[t['containerInstanceArn']]] = set()
                id_cluster_map[ci_ids[t['containerInstanceArn']]].add(cluster_names[t['clusterArn']])
                if ci_ids[t['containerInstanceArn']] not in id_td_map:
                    id_td_map[ci_ids[t['containerInstanceArn']]] = set()
                id_td_map[ci_ids[t['containerInstanceArn']]].add(get_td(t['taskDefinitionArn']))
            logger.debug('instance, cluster, task definition map created')
            for instance in instances:
                cluster_arns = id_cluster_map[instance['InstanceId']]
                task_definitions = id_td_map[instance['InstanceId']]
                ec2_instance = EC2Instance(self.config[aws_name], instance, cluster_arns, task_definitions)
                if self.config[aws_name]['filter']['connectable'] and not ec2_instance.is_connectable:
                    continue
                manager.add_instance(aws_name, ec2_instance)
            logger.info(f'Instance loaded: {aws_name}')
        manager.sort()
        return manager


class EC2Instance(object):
    DEFAULT_NAME = "UNKNOWN-NAME"

    def __init__(self, config, instance, clusters, task_definitions):
        self.config = config
        self.instance = instance
        self.clusters = clusters
        self.task_definitions = task_definitions

    @property
    def tags(self):
        return {t['Key']: t['Value'] for t in self.instance.get('Tags', {}) if t['Value'] != ''}

    @property
    def id(self):
        return self.instance['InstanceId']

    @property
    def name(self):
        if self.config['name-tag'] in self.tags:
            return self.tags[self.config['name-tag']]
        return self.id

    @property
    def type(self):
        return self.instance['InstanceType']

    @property
    def key_name(self):
        option = self.config['key-file']['default']
        key_name = self.instance.get('KeyName') if option == 'auto' else option
        override = self.config['key-file']
        for cluster, value in override.get('cluster', {}).items():
            if cluster in self.clusters:
                key_name = value
        for name, value in override.get('name', {}).items():
            if name in self.name:
                key_name = value
        return key_name

    @property
    def key_file(self):
        if self.key_name is None:
            return None

        key_file = self.config['ssh-path'] + '/' + self.key_name
        key_path = expanduser(key_file)

        if isfile(key_path):
            return key_path

        if key_path.endswith('.pem'):
            return key_path if isfile(key_path) else None

        pem_path = key_path + '.pem'
        return pem_path if isfile(pem_path) else None

    @property
    def private_ip(self):
        return self.instance.get('PrivateIpAddress')

    @property
    def public_ip(self):
        return self.instance.get('PublicIpAddress')

    @property
    def connect_ip(self):
        ip_type = self.config['connect-ip']['default']
        override = self.config['connect-ip']
        for cluster, value in override.get('cluster', {}).items():
            if cluster in self.clusters:
                ip_type = value
        for name, value in override.get('name', {}).items():
            if name in self.name:
                ip_type = value
        return self.public_ip if ip_type == 'public' else self.private_ip

    @property
    def user(self):
        user = self.config['user']['default']
        override = self.config['user']
        for cluster, value in override.get('cluster', {}).items():
            if cluster in self.clusters:
                user = value
        for name, value in override.get('name', {}).items():
            if name in self.name:
                user = value
        return user

    @property
    def has_key_file(self):
        return self.key_file is not None

    @property
    def is_running(self):
        log.info(self.instance['State'])
        return self.instance['State']['Name'] == 'running'

    @property
    def is_connectable(self):
        return self.is_running and self.has_key_file and self.connect_ip is not None
