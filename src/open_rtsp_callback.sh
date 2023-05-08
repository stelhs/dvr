#!/bin/sh

CNAME=$2
START_TIME=$3
VIDEO_FILE=$4
AUDIO_FILE=$5

#echo "cname=$CNAME&start_time=$START_TIME&video_file=$VIDEO_FILE&audio_file=$AUDIO_FILE" >> test
curl "http://localhost:8892/open_rtsp_cb?cname=$CNAME&start_time=$START_TIME&video_file=$VIDEO_FILE&audio_file=$AUDIO_FILE"
