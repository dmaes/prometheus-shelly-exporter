#! /usr/bin/env python3

import falcon
import json
import prometheus_client as prom
import re
import requests
from wsgiref import simple_server


class ShellyException(Exception):
  pass



class Metrics:
  def __init__(self, prefix=None, labels={}):
    self._prefix = prefix
    self._labels = labels
    self._metrics = {}

  def add(self, metric, value, labels={}, help="", type="gauge"):
    _labels = {**self._labels, **labels}
    _metric = f"{self._prefix}_{metric}" if self._prefix else metric
    if _metric not in self._metrics.keys():
      self._metrics[_metric] = {
            "help": help,
            "type": type,
            "values": [],
          }
    self._metrics[_metric]["values"] += [{"labels": _labels, "value": value}]

  @property
  def metrics(self):
    return self._metrics

  def collect(self):
    for name, metric in self._metrics.items():
      prom_metric = prom.Metric(name, metric["help"], metric["type"])
      for value in metric["values"]:
        prom_metric.add_sample(name, value=value["value"], labels=value["labels"])
      yield prom_metric

  @staticmethod
  def merge(metrics_list):
    metrics = Metrics()
    for item in metrics_list:
      for name, metric in item.metrics.items():
        for value in metric["values"]:
          metrics.add(name, value["value"], value["labels"], metric["help"], metric["type"])
    return metrics


class Shelly:
  def __init__(self, name, username, password):
    if name is None: raise ShellyException("'name' cannot be empty")
    self._name = name
    self._auth = None if None in (username, password) else (username, password)
    self._type = self.api("/shelly")["type"]
    self._metrics = {}

  @property
  def name(self):
    return self._name

  @property
  def type(self):
    return self._type

  @property
  def labels(self):
    return {
        "name": self.name,
        "type": self.type,
      }


  def api(self, path):
    try:
      _path = re.sub(r'^/', '', path)
      url = f"http://{self.name}/{_path}"
      req = requests.get(url, auth=self._auth)
      return req.json()
    except Exception as e:
      raise ShellyException(str(e))


  def _get_metrics_base(self):
    metrics = Metrics("shelly", self.labels)
    status = self.api("/status")
    metrics.add("wifi_sta_connected", status["wifi_sta"]["connected"])
    metrics.add("cloud_enabled", status["cloud"]["enabled"])
    metrics.add("cloud_connected", status["cloud"]["connected"])
    metrics.add("mqtt_connected", status["mqtt"]["connected"])
    metrics.add("serial", status["serial"])
    metrics.add("has_update", status["mqtt"]["connected"])
    metrics.add("ram_total", status["ram_total"])
    metrics.add("ram_free", status["ram_free"])
    metrics.add("fs_size", status["fs_size"])
    metrics.add("fs_free", status["fs_free"])
    metrics.add("uptime", status["uptime"], type="counter")
    return metrics


  def _get_metrics_plug(self):
    metrics = self._get_metrics_base()
    settings = self.api("/settings")
    metrics.add("max_power", settings["max_power"])
    metrics.add("led_status_disable", settings["led_status_disable"])
    metrics.add("led_power_disable", settings["led_power_disable"])
    status = self.api("/status")
    metrics.add("temperature", status["temperature"])
    metrics.add("overtemperature", status["overtemperature"])
    for i, r in enumerate(status["relays"]):
      labels = {"relay": str(i)}
      metrics.add("relay_ison", r["ison"], labels=labels)
      metrics.add("relay_has_timer", r["has_timer"], labels=labels)
      if r["has_timer"]:
        metrics.add("relay_timer_started", r["timer_started"], labels=labels)
        metrics.add("relay_timer_duration", r["timer_duration"], labels=labels)
        metrics.add("relay_timer_remaining", r["timer_remaining"], labels=labels)
      metrics.add("relay_overpower", r["overpower"], labels=labels)
    for i, m in enumerate(status["meters"]):
      labels = {"meter": str(i)}
      metrics.add("meter_power", m["power"], labels=labels)
      # metrics.add("meter_overpower", m["overpower"], labels=labels)
      metrics.add("meter_is_valid", m["is_valid"], labels=labels)
      metrics.add("meter_total", m["total"], labels=labels)
    return metrics


  def get_metrics(self):
    getters = {
        "SHPLG-S": self._get_metrics_plug
      }
    metrics = getters[self.type]() if self.type in getters.keys() else self._get_metrics_base()
    return metrics



class Prober:
  def on_get(self, req, resp):
    try:
      shelly = Shelly(req.get_param("target"), req.get_param("username"), req.get_param("password"))
      resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
      resp.text = prom.exposition.generate_latest(shelly.get_metrics())
    except ShellyException as e:
      resp.status = falcon.HTTP_400
      resp.text = str(e)


class Static:
  def __init__(self, targets, username, password):
    self._targets = targets
    self._username = username
    self._password = password

  def on_get(self, req, resp):
    metrics = []
    try:
      for target in self._targets:
        shelly = Shelly(target, self._username, self._password)
        metrics += [shelly.get_metrics()]
      metrics = Metrics.merge(metrics)
      resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
      resp.text = prom.exposition.generate_latest(metrics)
    except ShellyException as e:
      resp.status = falcon.HTTP_400
      resp.text = str(e)



def run(addr, port, statics=[], static_username=None, static_password=None):
  api = falcon.App()
  api.add_route('/metrics', Static(statics, static_username, static_password))
  api.add_route('/probe', Prober())
  httpd = simple_server.make_server(addr, port, api)
  httpd.serve_forever()


def cli():
  import argparse
  parser = argparse.ArgumentParser(description="""
Prometheus Exporter for Shelly devices.

This exporter will scrape the API endpoints of Shelly devices.
Device-specific metrics are auto-discovered based on the 'type' value of the '/shelly' endpoint.

2 endpoints are provided:
  * The '/probe' endpoint will do a single scrape of the target specified
    with the 'target' URL parameter.
    'username' and 'password' parameters can optionally be added if authentication is required.
  * The '/metrics' endpoint will scrape all devices specified at startup
    with the '-s|--static-targets' option.
    Other relevant flags are '-U|--username' and '-P|--password'.
""", formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('-l', '--listen-ip', dest='addr', default='0.0.0.0', help="IP address for the exporter to listen on. Default: 0.0.0.0")
  parser.add_argument('-p', '--listen-port', dest='port', type=int, default=9686, help="Port for the exporter to listen on. Default: 9686")
  parser.add_argument('-s', '--static-targets', dest='statics', nargs='*', help="List of static targets to scrape when querying /metrics")
  parser.add_argument('-U', '--username', dest='username', help="Username for the static targets (same for all)")
  parser.add_argument('-P', '--password', dest='password', help="Password for the static targets (same for all)")
  args = parser.parse_args()
  run(args.addr, args.port, args.statics, args.username, args.password)


if __name__ == '__main__':
  cli()
