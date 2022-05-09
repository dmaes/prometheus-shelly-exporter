#! /usr/bin/env python3

import falcon
import json
import os
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
      req = requests.get(url, auth=self._auth, timeout=5)
      return req.json()
    except Exception as e:
      raise ShellyException(str(e))


  def _get_metrics_base(self):
    metrics = Metrics("shelly", self.labels)
    status = self.api("/status")
    metrics.add("wifi_sta_connected", status["wifi_sta"]["connected"],
        help="Current status of the WiFi connection (connected or not)")
    metrics.add("cloud_enabled", status["cloud"]["enabled"],
        help="Current cloud connection status (enabled or not)")
    metrics.add("cloud_connected", status["cloud"]["connected"],
        help="Current cloud connection status (connected or not)")
    metrics.add("mqtt_connected", status["mqtt"]["connected"],
        help="MQTT connection status, when MQTT is enabled (connected or not)")
    metrics.add("serial", status["serial"],
        help="Cloud serial number")
    metrics.add("has_update", status["update"]["has_update"],
        help="Whether an update is available")
    metrics.add("ram_total", status["ram_total"],
        help="Total amount of system memory in bytes")
    metrics.add("ram_free", status["ram_free"],
        help="Available amount of system memory in bytes")
    metrics.add("fs_size", status["fs_size"],
        help="Total amount of the file system in bytes")
    metrics.add("fs_free", status["fs_free"],
        help="Available amount of the file system in bytes")
    metrics.add("uptime", status["uptime"], type="counter",
        help="Seconds elapsed since boot")
    return metrics


  def _get_metrics_plug(self):
    metrics = self._get_metrics_base()
    settings = self.api("/settings")
    status = self.api("/status")
    metrics.add("max_power", settings["max_power"],
        help="Overpower threshold in Watts")
    if self.type == "SHPLG-S":  # PlugS only settings
      metrics.add("led_status_disable", settings["led_status_disable"],
          help="Whether LED indication for connection status is enabled")
      metrics.add("led_power_disable", settings["led_power_disable"],
          help="Whether LED indication for output status is enabled")
      metrics.add("temperature", status["temperature"],
          help="internal device temperature in °C")
      metrics.add("overtemperature", status["overtemperature"],
          help="true when device has overheated")
    for i, r in enumerate(status["relays"]):
      labels = {"relay": str(i)}
      metrics.add("relay_ison", r["ison"], labels=labels,
          help="Whether the channel is turned ON or OFF")
      metrics.add("relay_has_timer", r["has_timer"], labels=labels,
          help="Whether a timer is currently armed for this channel")
      if r["has_timer"]:
        metrics.add("relay_timer_started", r["timer_started"], labels=labels,
            help="Unix timestamp of timer start; 0 if timer inactive or time not synced")
        metrics.add("relay_timer_duration", r["timer_duration"], labels=labels,
            help="Timer duration, s")
        metrics.add("relay_timer_remaining", r["timer_remaining"], labels=labels,
            help="If there is an active timer, shows seconds until timer elapses; 0 otherwise")
      metrics.add("relay_overpower", r["overpower"], labels=labels)
    for i, m in enumerate(status["meters"]):
      labels = {"meter": str(i)}
      metrics.add("meter_power", m["power"], labels=labels,
          help="Current real AC power being drawn, in Watts")
      # metrics.add("meter_overpower", m["overpower"], labels=labels)
      metrics.add("meter_is_valid", m["is_valid"], labels=labels,
          help="Whether power metering self-checks OK")
      metrics.add("meter_total", m["total"], labels=labels,
          help="Total energy consumed by the attached electrical appliance in Watt-minute")
    return metrics

  def _get_metrics_trv(self):
    metrics = self._get_metrics_base()
    settings = self.api("/settings")
    status = self.api("/status")
    metrics.add("bat_charge", status["bat"]["value"],
            help="Percentage of battery level")
    metrics.add("bat_voltage", status["bat"]["voltage"],
            help="Battery voltage")
    metrics.add("bat_charger", status["charger"],
            help="Boolean to show whether a charger is plugged in")
    for i, r in enumerate(status["thermostats"]):
        labels = {"thermostats": str(i)}
        metrics.add("pos", r["pos"], labels=labels,
            help="Position of thermostat pin")
        metrics.add("thermostat_enabled", r["target_t"]["enabled"], labels=labels,
            help="Whether the thermostat is enabled")
        metrics.add("thermostat_target_t", r["target_t"]["value"], labels=labels,
            help="Thermostat target temperature")
#        metrics.add("thermostat_target_unit", r["target_t"]["units"], labels=labels,
#            help="Unit of the target temperature, either F or C")
        metrics.add("thermostat_measured_temperature", r["tmp"]["value"], labels=labels,
            help="Thermostat measured temperature")
#        metrics.add("thermostat_measured_unit", r["tmp"]["units"], labels=labels,
#            help="Unit of the measured temperature, either F or C")
        metrics.add("thermostat_measured_valid", r["tmp"]["is_valid"], labels=labels,
                help="Whether the temperature measurement is valid")
        metrics.add("thermostat_is_scheduled", r["schedule"], labels=labels,
            help="Whether the thermostat is following a schedule")
        metrics.add("thermostat_schedule_profile", r["schedule_profile"], labels=labels,
            help="Current thermostat profile")
        metrics.add("thermostat_boost_minutes", r["boost_minutes"], labels=labels,
            help="Length of initial warm-up boost, in minutes")
    return metrics

  def _get_metrics_HT(self):
    metrics = self._get_metrics_base()
    settings = self.api("/settings")
    status = self.api("/status")
    metrics.add("bat_charge", status["bat"]["value"],
            help="Percentage of battery level")
    metrics.add("bat_voltage", status["bat"]["voltage"],
            help="Battery voltage")
    metrics.add("humidity", status["hum"]["value"],
            help="Air humidity, in %rH")
    metrics.add("humidity_valid", status["hum"]["is_valid"],
            help="Whether the humidity measurement is valid")
    metrics.add("temperature", status["tmp"]["value"],
            help="Air temperature")
    metrics.add("temperature_valid", status["tmp"]["is_valid"],
            help="Whether the temperature measurement is valid")
    return metrics


  def get_metrics(self):
    getters = {
        "SHPLG-S":  self._get_metrics_plug,
        "SHTRV-01": self._get_metrics_trv,
        "SHHT-1":   self._get_metrics_HT
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
    for target in self._targets:
      try:
        shelly = Shelly(target, self._username, self._password)
        metrics += [shelly.get_metrics()]
      except ShellyException as e:
        print(e)
        m_down = Metrics("shelly", {"name": target})
        m_down.add("down", True, help="Shelly can't be reached")
        metrics += [m_down]
    metrics = Metrics.merge(metrics)
    resp.set_header('Content-Type', prom.exposition.CONTENT_TYPE_LATEST)
    resp.text = prom.exposition.generate_latest(metrics)



def run(addr, port, statics=[], static_username=None, static_password=None):
  api = falcon.App()
  api.add_route('/metrics', Static(statics, static_username, static_password))
  api.add_route('/probe', Prober())
  httpd = simple_server.make_server(addr, port, api)
  httpd.serve_forever()


def cli_env(env, default=None):
  _env = f"SHELLY_{env}"
  return os.environ.get(_env) if os.environ.get(_env) is not None else default


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
""", formatter_class=argparse.RawDescriptionHelpFormatter,
      epilog="All parameters can be supplied as env vars in 'SHELLY_<LONG_ARG>' form (e.g. 'SHELLY_LISTEN_PORT')")
  parser.add_argument('-l', '--listen-ip', dest='listen_ip', default=cli_env('LISTEN_IP', '0.0.0.0'), help="IP address for the exporter to listen on. Default: 0.0.0.0")
  parser.add_argument('-p', '--listen-port', dest='listen_port', type=int, default=cli_env('LISTEN_PORT', 9686), help="Port for the exporter to listen on. Default: 9686")
  parser.add_argument('-s', '--static-targets', dest='static_targets', default=cli_env('STATIC_TARGETS'), help="Comma-separated list of static targets to scrape when querying /metrics")
  parser.add_argument('-U', '--username', dest='username', default=cli_env('USERNAME'), help="Username for the static targets (same for all)")
  parser.add_argument('-P', '--password', dest='password', default=cli_env('PASSWORD'), help="Password for the static targets (same for all)")
  args = parser.parse_args()
  run(args.listen_ip, args.listen_port, args.static_targets.split(','), args.username, args.password)


if __name__ == '__main__':
  cli()
