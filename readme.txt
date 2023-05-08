Installing DVR

1) mkdir dvr; cd dvr

2) git clone https://github.com/stelhs/live555.git; git checkout video-recorder

3) git clone https://github.com/stelhs/sr90lib.git

4) setup aufs storage from some USB mass storage devices
    4.1) mkfs.ext4 for new USB mass storage devices
    4.2) create multiple directories
        mkdir /storage
        mkdir /storage1
        mkdir /storage2

    4.3) mark it as not mounted
        touch /storage/NOT_MOUNTED
        touch /storage1/NOT_MOUNTED
        touch /storage2/NOT_MOUNTED

    4.4) copy udev rules
        cp rootfs/udev/80-usb_storage.rules /etc/udev/rules.d/
        cp rootfs/udev/mount_storage.sh /etc/udev/rules.d/
        cp rootfs/udev/umount_storage.sh /etc/udev/rules.d/
        cp rootfs/udev/remount_overlay.sh /etc/udev/rules.d/

    4.5) modify /etc/udev/rules.d/80-usb_storage.rules for
    corresponding USB mass storage devices. This will require:
        sudo udevadm monitor --environment
        sudo systemctl restart udev.service
        sudo udevadm control --reload

    4.6) added option to /etc/udev/udev.conf
            event_timeout=1200
        and
            sudo systemctl restart udev.service
