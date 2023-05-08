#!/bin/bash
# DEVNAME - aka /dev/sdb

function log() {
    echo $1 | logger -t umount_storage
}


if [ "$DEVNAME" = "" ]; then
    log "no device name"
    exit 0
fi

log "umount $DEVNAME"
umount -l $DEVNAME

/etc/udev/rules.d/remount_overlay.sh

