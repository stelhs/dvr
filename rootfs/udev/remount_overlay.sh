#!/bin/bash

MPOINT1="/storage1"
MPOINT2="/storage2"
MPOINT="/storage"

is_mounted() {
    mount | awk -v DIR="$1" '{if ($3 == DIR) { exit 0}} ENDFILE{exit -1}'
}


if is_mounted $MPOINT; then
    umount -l $MPOINT
fi

if is_mounted $MPOINT1 && is_mounted $MPOINT2; then
    mount -t aufs -o br=$MPOINT1=rw:$MPOINT2=rw,create=mfs,sum,_netdev none $MPOINT
    exit 0
fi

if is_mounted $MPOINT1; then
    mount -t aufs -o br=$MPOINT1=rw,create=mfs,sum,_netdev none $MPOINT
    exit 0
fi

if is_mounted $MPOINT2; then
    mount -t aufs -o br=$MPOINT2=rw,create=mfs,sum,_netdev none $MPOINT
    exit 0
fi

