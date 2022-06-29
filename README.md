# prometheus-shelly-exporter
Prometheus Exporter for Shelly devices

**If you want support for another device, or metrics for an existing device are missing,
please open an issue or PR.**
I only implemented for the devices I personally have.

## Help
```
usage: shelly_exporter.py [-h] [-c CONFIG_FILE] [-l LISTEN_IP]
                          [-p LISTEN_PORT] [-s STATIC_TARGETS] [-U USERNAME]
                          [-P PASSWORD] [-t TIMEOUT] [-C TARGETCFG]
                          [-f METRICS_FILE] [--s3-bucket S3_BUCKET]
                          [--s3-url S3_URL] [--s3-key-id S3_KEY_ID]
                          [--s3-secret-key S3_SECRET_KEY]
                          [--s3-verify S3_VERIFY]

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

options:
  -h, --help            show this help message and exit
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        Config file. If specified, all other params will be
                        ignored.
  -l LISTEN_IP, --listen-ip LISTEN_IP
                        IP address for the exporter to listen on. Default:
                        0.0.0.0
  -p LISTEN_PORT, --listen-port LISTEN_PORT
                        Port for the exporter to listen on. Default: 9686
  -s STATIC_TARGETS, --static-targets STATIC_TARGETS
                        Comma-separated list of static targets to scrape when
                        querying /metrics
  -U USERNAME, --username USERNAME
                        Username for the static targets (same for all)
  -P PASSWORD, --password PASSWORD
                        Password for the static targets (same for all)
  -t TIMEOUT, --timeout TIMEOUT
                        Timeout (in seconds) to use when Scraping shelly
                        devices. Default: 5
  -C TARGETCFG, --targetcfg TARGETCFG
                        YAML or JSON string containing target config. See
                        example config for help.
  -f METRICS_FILE, --metrics-file METRICS_FILE
                        Pickle file or S3 path to save metrics too (from
                        /probe?save=true). Default: metrics.pkl
  --s3-bucket S3_BUCKET
                        S3 bucket to save metrics file in. Usefull in dynamic
                        containerized setup
  --s3-url S3_URL       Optional S3 endpoint url to use. Must include
                        http/https, if used.
  --s3-key-id S3_KEY_ID
                        Optinal Access Key ID to use when connection to S3
  --s3-secret-key S3_SECRET_KEY
                        Optional Secret Access Key to use when connection to
                        S3
  --s3-verify S3_VERIFY
                        Set 'false' to not verify S3 SSL, or path to a custom
                        CA to use.

All parameters can be supplied as env vars in 'SHELLY_<LONG_ARG>' form (e.g. 'SHELLY_LISTEN_PORT')
```
