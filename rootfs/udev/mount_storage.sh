#!/bin/bash
# DEVNAME - aka /dev/sdb
# $1 - mount point name
MPOINT=$1
SNAME=`basename $MPOINT`

function log() {
    echo $1 | logger -t mount_storage
    now=`date "+%F %T"`
    echo $now: $1 >> "/tmp/mount_storage_$SNAME"
}

function do_for_sighup() {
     log "SIGHUP received, abort long operation"
     mk_fs $DEVNAME
     if test "$?" != "0"; then
         log "can't mkfs"
         exit 0
     fi
}

trap 'do_for_sighup' 1

function mk_fs() {
	dev=$1
	log "cleaning $dev"
	dd if=/dev/zero of=$dev bs=1M count=1000 >> /tmp/mount_storage_$MPOINT 2>&1
	log "make fs $dev"
	mkfs.ext4 $dev >> /tmp/mount_storage_$SNAME 2>&1
	return $?
}

log "start mount_storage.sh"


if [ "$DEVNAME" = "" ]; then
    log "no device name"
    exit 0
fi

if [ "$MPOINT" = "" ]; then
    log "no mount point name"
    exit 0
fi


log "run USB storage mounting $DEVNAME $MPOINT"

log "run fsck $DEVNAME"
fsck.ext4 -y $DEVNAME >> /tmp/mount_storage_$SNAME 2>&1
if [ "$?" != "0" ]; then
	log "fsck error"
	mk_fs $DEVNAME
	if test "$?" != "0"; then
		log "can't mkfs"
		exit 0
	fi
fi

log "mount $DEVNAME $MPOINT"
mount $DEVNAME $MPOINT
if [ "$?" == "0" ]; then
    log "success"
    /etc/udev/rules.d/remount_overlay.sh
    exit 0
fi

log "can't mount $DEVNAME"

