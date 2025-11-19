#!/bin/bash
# Restart washdb-bot service
sudo systemctl restart washdb-bot
sleep 3
sudo systemctl status washdb-bot --no-pager -l
