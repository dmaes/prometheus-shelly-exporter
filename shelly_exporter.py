#! /usr/bin/env python3

import falcon
import json
import prometheus_client as prom
import re
import requests
from collections import defaultdict
from wsgiref import simple_server


class TargetException(Exception):
  pass


class Target:
  def __init__(self, target, username, password):
    if target is None: raise TargetException("'target' cannot be empty")
    self._target = target
    self._username = username
    self._password = password
    self._type = self.get("/shelly")["type"]


  @property
  def type(self): return self._type


  @property
  def _auth(self):
    if self._username is None or self._password is None: return None
    return (self._username, self._password)


  def get(self, path):
    try:
      _path = re.sub(r'^/', '', path)
      url = f"http://{self._target}/{_path}"
      req = requests.get(url, auth=self._auth)
      return req.json()
    except Exception as e:
      raise TargetException(str(e))



class Collector:
  def __init__(self, target):
    self._target = target
    self._labels = {}
    self._labels["type"] = self._target.type
    self._metrics = {}


  def _set_metric(self, metric, value, labels={}, help="", type="gauge"):
    if metric not in self._metrics.keys():
      self._metrics[metric] = {
            "help": help,
            "type": type,
            "values": [],
          }
    self._metrics[metric]["values"] += [{"labels": labels, "value": value}]


  def _set_metrics(self):
    status = self._target.get("/status")
    self._set_metric("wifi_sta_connected", status["wifi_sta"]["connected"])
    self._set_metric("cloud_enabled", status["cloud"]["enabled"])
    self._set_metric("cloud_connected", status["cloud"]["connected"])
    self._set_metric("mqtt_connected", status["mqtt"]["connected"])
    self._set_metric("serial", status["serial"])
    self._set_metric("has_update", status["mqtt"]["connected"])
    self._set_metric("ram_total", status["ram_total"])
    self._set_metric("ram_free", status["ram_free"])
    self._set_metric("fs_size", status["fs_size"])
    self._set_metric("fs_free", status["fs_free"])
    self._set_metric("uptime", status["uptime"], type="counter")


  def collect(self):
    self._set_metrics()

    for k, v in self._metrics.items():
      mname = f"shelly_{k}"
      metric = prom.Metric(mname, v["help"], v["type"])
      for val in v["values"]:
        metric.add_sample(mname, value=val["value"], labels={**self._labels, **val["labels"]})
      yield metric



class SHPLGCollector(Collector):
  def _set_metrics(self):
    super()._set_metrics()
    settings = self._target.get("/settings")
    self._set_metric("max_power", settings["max_power"])
    self._set_metric("led_status_disable", settings["led_status_disable"])
    self._set_metric("led_power_disable", settings["led_power_disable"])
    status = self._target.get("/status")
    self._set_metric("temperature", status["temperature"])
    self._set_metric("overtemperature", status["overtemperature"])
    for i, r in enumerate(status["relays"]):
      labels = {"relay": str(i)}
      self._set_metric("relay_ison", r["ison"], labels=labels)
      self._set_metric("relay_has_timer", r["has_timer"], labels=labels)
      if r["has_timer"]:
        self._set_metric("relay_timer_started", r["timer_started"], labels=labels)
        self._set_metric("relay_timer_duration", r["timer_duration"], labels=labels)
        self._set_metric("relay_timer_remaining", r["timer_remaining"], labels=labels)
      self._set_metric("relay_overpower", r["overpower"], labels=labels)
    for i, m in enumerate(status["meters"]):
      labels = {"meter": str(i)}
      self._set_metric("meter_power", m["power"], labels=labels)
      # self._set_metric("meter_overpower", m["overpower"], labels=labels)
      self._set_metric("meter_is_valid", m["is_valid"], labels=labels)
      self._set_metric("meter_total", m["total"], labels=labels)


collectors = defaultdict(lambda: Collector)
collectors["SHPLG-S"] = SHPLGCollector



class Prober:
  def on_get(self, req, resp):
    resp.content_type = falcon.MEDIA_TEXT

    try:
      target = Target(req.get_param("target"), req.get_param("username"), req.get_param("password"))
      resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
      resp.text = prom.exposition.generate_latest(collectors[target.type](target))
    except TargetException as e:
      resp.status = falcon.HTTP_400
      resp.text = str(e)


  def _common_metrics(self, target):
    return json.dumps(target.get("/settings"))



def run(addr, port):
  api = falcon.App()
  api.add_route('/probe', Prober())
  httpd = simple_server.make_server(addr, port, api)
  httpd.serve_forever()



if __name__ == '__main__':
  run('0.0.0.0', 9999)
