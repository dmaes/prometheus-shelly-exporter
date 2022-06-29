#! /usr/bin/env python3

import falcon
import json
import os
import pickle
import prometheus_client as prom
import re
import requests
import time
from wsgiref import simple_server


class ShellyException(Exception):
  pass



class Metrics:
  def __init__(self, prefix=None, labels={}):
    self._prefix = prefix
    self._labels = labels
    self._metrics = {}

  def add(self, metric, value, labels={}, help='', type='gauge'):
    _labels = {**self._labels, **labels}
    _metric = f"{self._prefix}_{metric}" if self._prefix else metric
    if _metric not in self._metrics.keys():
      self._metrics[_metric] = {
            'help': help,
            'type': type,
            'values': [],
          }
    self._metrics[_metric]['values'] += [{'labels': _labels, 'value': value}]

  @property
  def metrics(self):
    return self._metrics

  def collect(self):
    for name, metric in self._metrics.items():
      prom_metric = prom.Metric(name, metric['help'], metric['type'])
      for value in metric['values']:
        prom_metric.add_sample(name, value=value['value'], labels=value['labels'])
      yield prom_metric

  @staticmethod
  def merge(metrics_list):
    metrics = Metrics()
    for item in metrics_list:
      for name, metric in item.metrics.items():
        for value in metric['values']:
          metrics.add(name, value['value'], value['labels'], metric['help'], metric['type'])
    return metrics



class MetricsFile:
  def __init__(self, path,
      s3_bucket=None, s3_url=None, s3_key_id='', s3_secret_key='', s3_verify=None):
    self._path = path
    self._s3_bucket = s3_bucket
    self._s3_url = s3_url
    self._s3_key_id = s3_key_id
    self._s3_secret_key = s3_secret_key
    self._s3_verify = s3_verify
    if self._s3_bucket:
      import random
      import string
      self._s3_tmp = '.tmp-' + ''.join(random.choice(string.ascii_lowercase) for i in range(4))
      while os.path.exists(self._s3_tmp):
        self._s3_tmp = '.tmp-' + ''.join(random.choice(string.ascii_lowercase) for i in range(4))
      import boto3
      self._init_s3()
    else: self._init_file()

  def _init_file(self):
    if not os.path.isfile(self._path):
      self._write_metrics({})
      print(f"Initialized metrics pickle on {self._path}")
    else: print(f"Re-using existing metrics pickle from {self._path}")

  def _get_s3(self):
    return boto3.client('s3', endpoint_url=self._s3_url, verify=self._s3_verify,
        aws_access_key_id=self._s3_key_id, aws_secret_access_key=self._s3_secret_key)

  def _init_s3(self):
    s3 = self._get_s3()
    for c in s3.list_objects(Bucket=self._s3_bucket)['Contents']:
      if self._path == c['Key']:
        print(f"Re-using existing metrics pickle from {self._path} on S3")
        return
    self._write_metrics({})
    print(f"Initialized metrics pickle on {self._path} on S3")

  def get_metrics(self):
    path = self._s3_tmp if self._s3_bucket else self._path
    if self._s3_bucket: self._get_s3().download_file(self._s3_bucket, self._path, path)
    with open(path, 'rb') as pkl: metrics = pickle.load(pkl)
    if self._s3_bucket: os.remove(path)
    return metrics

  def _write_metrics(self, metrics):
    path = self._s3_tmp if self._s3_bucket else self._path
    with open(path, 'wb') as pkl: pickle.dump(metrics, pkl)
    if not self._s3_bucket: return
    s3 = self._get_s3()
    s3.upload_file(path, self._s3_bucket, self._path)
    os.remove(path)

  def add_metrics(self, name, metrics):
    all_metrics = self.get_metrics()
    all_metrics[name] = metrics
    self._write_metrics(all_metrics)



class Shelly:
  def __init__(self, name, username=None, password=None, timeout=5, extra_labels={}):
    if name is None: raise ShellyException("'name' cannot be empty")
    self._name = name
    self._auth = None if None in (username, password) else (username, password)
    self._timeout = timeout
    self._type = self.api('/shelly')['type']
    self._extra_labels = extra_labels
    self._metrics = {}

  @staticmethod
  def create_with_cfg(name, targetcfg, username=None, password=None, timeout=5, extra_labels={}):
    cfg = targetcfg[name] if name in targetcfg.keys() else {}
    return Shelly(**{ 'username': username, 'password': password, 'timeout': timeout,
      'extra_labels': extra_labels, **cfg, 'name': name })

  @property
  def name(self):
    return self._name

  @property
  def type(self):
    return self._type

  @property
  def labels(self):
    return {
        **self._extra_labels,
        'name': self.name,
        'type': self.type,
      }


  def api(self, path):
    try:
      _path = re.sub(r'^/', '', path)
      url = f"http://{self.name}/{_path}"
      req = requests.get(url, auth=self._auth, timeout=self._timeout)
      return req.json()
    except Exception as e:
      raise ShellyException(str(e))


  def _get_metrics_base(self):
    metrics = Metrics('shelly', self.labels)
    status = self.api('/status')
    metrics.add('wifi_sta_connected', status['wifi_sta']['connected'],
        help='Current status of the WiFi connection (connected or not)')
    metrics.add('cloud_enabled', status['cloud']['enabled'],
        help='Current cloud connection status (enabled or not)')
    metrics.add('cloud_connected', status['cloud']['connected'],
        help='Current cloud connection status (connected or not)')
    metrics.add('mqtt_connected', status['mqtt']['connected'],
        help='MQTT connection status, when MQTT is enabled (connected or not)')
    metrics.add('serial', status['serial'],
        help='Cloud serial number')
    metrics.add('has_update', status['update']['has_update'],
        help='Whether an update is available')
    metrics.add('ram_total', status['ram_total'],
        help='Total amount of system memory in bytes')
    metrics.add('ram_free', status['ram_free'],
        help='Available amount of system memory in bytes')
    metrics.add('fs_size', status['fs_size'],
        help='Total amount of the file system in bytes')
    metrics.add('fs_free', status['fs_free'],
        help='Available amount of the file system in bytes')
    metrics.add('uptime', status['uptime'], type='counter',
        help='Seconds elapsed since boot')
    return metrics


  def _get_metrics_plug(self):
    metrics = self._get_metrics_base()
    settings = self.api('/settings')
    status = self.api('/status')
    metrics.add('max_power', settings['max_power'],
        help='Overpower threshold in Watts')
    if self.type == 'SHPLG-S':  # PlugS only settings
      metrics.add('led_status_disable', settings['led_status_disable'],
          help='Whether LED indication for connection status is enabled')
      metrics.add('led_power_disable', settings['led_power_disable'],
          help='Whether LED indication for output status is enabled')
      metrics.add('temperature', status['temperature'],
          help='internal device temperature in °C')
      metrics.add('overtemperature', status['overtemperature'],
          help='true when device has overheated')
    for i, r in enumerate(status['relays']):
      labels = {'relay': str(i)}
      metrics.add('relay_ison', r['ison'], labels=labels,
          help='Whether the channel is turned ON or OFF')
      metrics.add('relay_has_timer', r['has_timer'], labels=labels,
          help='Whether a timer is currently armed for this channel')
      if r['has_timer']:
        metrics.add('relay_timer_started', r['timer_started'], labels=labels,
            help='Unix timestamp of timer start; 0 if timer inactive or time not synced')
        metrics.add('relay_timer_duration', r['timer_duration'], labels=labels,
            help='Timer duration, s')
        metrics.add('relay_timer_remaining', r['timer_remaining'], labels=labels,
            help='If there is an active timer, shows seconds until timer elapses; 0 otherwise')
      metrics.add('relay_overpower', r['overpower'], labels=labels)
    for i, m in enumerate(status['meters']):
      labels = {'meter': str(i)}
      metrics.add('meter_power', m['power'], labels=labels,
          help='Current real AC power being drawn, in Watts')
      # metrics.add('meter_overpower', m['overpower'], labels=labels)
      metrics.add('meter_is_valid', m['is_valid'], labels=labels,
          help='Whether power metering self-checks OK')
      metrics.add('meter_total', m['total'], labels=labels,
          help='Total energy consumed by the attached electrical appliance in Watt-minute')
    return metrics

  def _get_metrics_trv(self):
    metrics = self._get_metrics_base()
    settings = self.api('/settings')
    status = self.api('/status')
    metrics.add('bat_charge', status['bat']['value'],
            help='Percentage of battery level')
    metrics.add('bat_voltage', status['bat']['voltage'],
            help='Battery voltage')
    metrics.add('bat_charger', status['charger'],
            help='Boolean to show whether a charger is plugged in')
    for i, r in enumerate(status['thermostats']):
        labels = {'thermostats': str(i)}
        metrics.add('pos', r['pos'], labels=labels,
            help='Position of thermostat pin')
        metrics.add('thermostat_enabled', r['target_t']['enabled'], labels=labels,
            help='Whether the thermostat is enabled')
        metrics.add('thermostat_target_t', r['target_t']['value'], labels=labels,
            help='Thermostat target temperature')
#        metrics.add('thermostat_target_unit', r['target_t']['units'], labels=labels,
#            help='Unit of the target temperature, either F or C')
        metrics.add('thermostat_measured_temperature', r['tmp']['value'], labels=labels,
            help='Thermostat measured temperature')
#        metrics.add('thermostat_measured_unit', r['tmp']['units'], labels=labels,
#            help='Unit of the measured temperature, either F or C')
        metrics.add('thermostat_measured_valid', r['tmp']['is_valid'], labels=labels,
                help='Whether the temperature measurement is valid')
        metrics.add('thermostat_is_scheduled', r['schedule'], labels=labels,
            help='Whether the thermostat is following a schedule')
        metrics.add('thermostat_schedule_profile', r['schedule_profile'], labels=labels,
            help='Current thermostat profile')
        metrics.add('thermostat_boost_minutes', r['boost_minutes'], labels=labels,
            help='Length of initial warm-up boost, in minutes')
    return metrics

  def _get_metrics_ht(self):
    metrics = self._get_metrics_base()
    settings = self.api('/settings')
    status = self.api('/status')
    metrics.add('bat_charge', status['bat']['value'],
            help='Percentage of battery level')
    metrics.add('bat_voltage', status['bat']['voltage'],
            help='Battery voltage')
    metrics.add('humidity', status['hum']['value'],
            help='Air humidity, in %rH')
    metrics.add('humidity_valid', status['hum']['is_valid'],
            help='Whether the humidity measurement is valid')
    metrics.add('temperature', status['tmp']['value'],
            help='Air temperature')
    metrics.add('temperature_valid', status['tmp']['is_valid'],
            help='Whether the temperature measurement is valid')
    return metrics


  def get_metrics(self):
    getters = {
        'SHPLG-S':  self._get_metrics_plug,
        'SHTRV-01': self._get_metrics_trv,
        'SHHT-1':   self._get_metrics_ht
      }
    metrics = getters[self.type]() if self.type in getters.keys() else self._get_metrics_base()
    return metrics



class Prober:
  def __init__(self, targetcfg, metrics_file, timeout):
    self._targetcfg = targetcfg
    self._metrics_file = metrics_file
    self._timeout = timeout

  def on_get(self, req, resp):
    try:
      shelly = Shelly.create_with_cfg(req.get_param('target'), self._targetcfg,
          req.get_param('username'), req.get_param('password'), self._timeout)
      metrics = shelly.get_metrics()
      if req.get_param('save') == 'true':
        metrics.add('probetime', int(time.time()), type='counter',
            help='Unixtime this target was probed and saved.')
        self._metrics_file.add_metrics(shelly.name, metrics)
      resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
      resp.text = prom.exposition.generate_latest(metrics)
    except ShellyException as e:
      resp.status = falcon.HTTP_400
      resp.text = str(e)


class Static:
  def __init__(self, targetcfg, targets, username, password, metrics_file, timeout):
    self._targetcfg = targetcfg
    self._targets = targets
    self._username = username
    self._password = password
    self._metrics_file = metrics_file
    self._timeout = timeout

  def on_get(self, req, resp):
    metrics = []
    for target in self._targets:
      try:
        shelly = Shelly(target, self._username, self._password, self._timeout)
        shelly = Shelly.create_with_cfg(target, self._targetcfg, self._username,
            self._password, self._timeout)
        metrics += [shelly.get_metrics()]
      except ShellyException as e:
        print(e)
        m_down = Metrics('shelly', {'name': target})
        m_down.add('down', True, help="Shelly can't be reached")
        metrics += [m_down]
    for target, metric in self._metrics_file.get_metrics().items():
      if target not in self._targets: metrics += [metric]
    metrics = Metrics.merge(metrics)
    resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
    resp.text = prom.exposition.generate_latest(metrics)


def run(cfg):
  api = falcon.App()
  metrics_file = MetricsFile(cfg['metrics_file'], cfg['s3_bucket'], cfg['s3_url'],
      cfg['s3_key_id'], cfg['s3_secret_key'], cfg['s3_verify'])
  api.add_route('/metrics', Static(cfg['targetcfg'], cfg['static_targets'], cfg['username'],
    cfg['password'], metrics_file, cfg['timeout']))
  api.add_route('/probe', Prober(cfg['targetcfg'], metrics_file, cfg['timeout']))
  httpd = simple_server.make_server(cfg['listen_ip'], cfg['listen_port'], api)
  httpd.serve_forever()


def cli_env(env, default=None):
  _env = f"SHELLY_{env}"
  return os.environ.get(_env) if os.environ.get(_env) is not None else default

default_cfg = {
  'listen_ip': '0.0.0.0',
  'listen_port': 9686,
  'timeout': 5,
  'metrics_file': 'metrics.pkl',
  'static_targets': [],
  'username': None,
  'password': None,
  'targetcfg': {},
  's3_bucket': None,
  's3_url': None,
  's3_key_id': '',
  's3_secret_key': '',
  's3_verify': None,
}

def cli():
  import argparse
  parser = argparse.ArgumentParser(description='''
Prometheus Exporter for Shelly devices.

This exporter will scrape the API endpoints of Shelly devices.
Device-specific metrics are auto-discovered based on the 'type' value of the '/shelly' endpoint.

2 endpoints are provided:
  * The '/probe' endpoint will do a single scrape of the target specified
    with the 'target' URL parameter.
    'username' and 'password' parameters can optionally be added if authentication is required.
    If 'save' parameter is set to 'true', metrics will aditionally be saved and included in the
    results of the '/metrics' endpoint (Use-case are battery-powered devices that are in sleep mode
    most of the time and wake up to push metrics. Configure /probe URL as URL to push updates to on
    the battery-powered device).
  * The '/metrics' endpoint will scrape all devices specified at startup
    with the '-s|--static-targets' option, and those saved from the '/probe' endpoint
    (with static targets overwriting saved probes, if one exists as both).
    Other relevant flags are '-U|--username' and '-P|--password'.
''', formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog="All parameters can be supplied as env vars in 'SHELLY_<LONG_ARG>' form (e.g. 'SHELLY_LISTEN_PORT')")
  parser.add_argument('-c', '--config-file', dest='config_file', default=cli_env('CONFIG_FILE'),
      help='Config file. If specified, all other params will be ignored.')
  parser.add_argument('-l', '--listen-ip', dest='listen_ip', default=cli_env('LISTEN_IP'),
      help='IP address for the exporter to listen on. Default: 0.0.0.0')
  parser.add_argument('-p', '--listen-port', dest='listen_port', type=int,
      default=cli_env('LISTEN_PORT'), help='Port for the exporter to listen on. Default: 9686')
  parser.add_argument('-s', '--static-targets', dest='static_targets',
      default=cli_env('STATIC_TARGETS'),
      help='Comma-separated list of static targets to scrape when querying /metrics')
  parser.add_argument('-U', '--username', dest='username', default=cli_env('USERNAME'),
      help='Username for the static targets (same for all)')
  parser.add_argument('-P', '--password', dest='password', default=cli_env('PASSWORD'),
      help='Password for the static targets (same for all)')
  parser.add_argument('-t', '--timeout', dest='timeout', default=cli_env('TIMEOUT'),
      help='Timeout (in seconds) to use when Scraping shelly devices. Default: 5')
  parser.add_argument('-C', '--targetcfg', dest='targetcfg', default=cli_env('TARGETCFG'),
      help='YAML or JSON string containing target config. See example config for help.')
  parser.add_argument('-f', '--metrics-file', dest='metrics_file', default=cli_env('METRICS_FILE'),
      help='Pickle file or S3 path to save metrics too (from /probe?save=true). Default: metrics.pkl')
  parser.add_argument('--s3-bucket', dest='s3_bucket', default=cli_env('S3_BUCKET'),
      help='S3 bucket to save metrics file in. Usefull in dynamic containerized setup')
  parser.add_argument('--s3-url', dest='s3_url', default=cli_env('S3_URL'),
      help='Optional S3 endpoint url to use. Must include http/https, if used.')
  parser.add_argument('--s3-key-id', dest='s3_key_id', default=cli_env('S3_KEY_ID'),
      help='Optinal Access Key ID to use when connection to S3')
  parser.add_argument('--s3-secret-key', dest='s3_secret_key', default=cli_env('S3_SECRET_KEY'),
      help='Optional Secret Access Key to use when connection to S3')
  parser.add_argument('--s3-verify', dest='s3_verify', default=cli_env('S3_VERIFY'),
      help="Set 'false' to not verify S3 SSL, or path to a custom CA to use.")
  args = parser.parse_args()
  cfg = default_cfg
  if args.config_file:
    import yaml
    with open(args.config_file) as file: cfg = { **default_cfg, **yaml.safe_load(file) }
  else:
    if args.listen_ip: cfg['listen_ip'] = args.listen_ip
    if args.listen_port: cfg['listen_port'] = args.listen_port
    if args.static_targets: cfg['static_targets'] = args.listen_port.split(',')
    if args.username: cfg['username'] = args.username
    if args.password: cfg['password'] = args.password
    if args.timeout: cfg['timeout'] = args.timeout
    if args.targetcfg: cfg['targetcfg'] = yaml.safe_load(args.targetcfg)
    if args.metrics_file: cfg['metrics_file'] = args.metrics_file
    if args.s3_bucket: cfg['s3']['bucket'] = args.s3_bucket
    if args.s3_url: cfg['s3_url'] = args.s3_url
    if args.s3_key_id: cfg['s3_key_id'] = args.s3_key_id
    if args.s3_secret_key: cfg['s3_secret_key'] = args.s3_secret_key
    if args.s3_verify: cfg['s3_verify'] = False if args.s3_verify == 'false' else args.s3_verify
  run(cfg)


if __name__ == '__main__':
  cli()
