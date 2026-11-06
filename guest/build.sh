#!/bin/sh
# Build the sandbox guest: kernel + minimal initramfs (busybox, agent, memload,
# virtio_mem module). Nothing needs root: the kernel is taken from the Ubuntu
# package via "apt download", the module from the matching package or from
# /lib/modules of the host.
#
# Usage: guest/build.sh [KERNEL_VERSION]      (default: 7.0.0-38-generic)
set -eu

KVER=${1:-7.0.0-38-generic}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/../build
mkdir -p "$OUT/pkg" "$OUT/root/bin" "$OUT/root/lib"

# Kernel image.
if [ ! -f "$OUT/vmlinuz" ]; then
	(cd "$OUT/pkg" && apt download "linux-image-unsigned-$KVER")
	dpkg-deb -x "$OUT"/pkg/linux-image-unsigned-"$KVER"_*.deb "$OUT/pkg/x"
	cp "$OUT/pkg/x/boot/vmlinuz-$KVER" "$OUT/vmlinuz"
fi

# virtio_mem module of the same version.
MOD=/lib/modules/$KVER/kernel/drivers/virtio/virtio_mem.ko.zst
if [ ! -f "$MOD" ]; then
	(cd "$OUT/pkg" && apt download "linux-modules-$KVER")
	dpkg-deb -x "$OUT"/pkg/linux-modules-"$KVER"_*.deb "$OUT/pkg/m"
	MOD=$OUT/pkg/m$MOD
fi
zstd -q -d -f "$MOD" -o "$OUT/root/lib/virtio_mem.ko"

# Static helpers.
cp "$(command -v busybox)" "$OUT/root/bin/busybox"
gcc -O2 -static -o "$OUT/root/bin/memload" "$HERE/memload.c"
install -m 0755 "$HERE/init" "$OUT/root/init"

(cd "$OUT/root" && find . | cpio -o -H newc --quiet | gzip -9) > "$OUT/initramfs.gz"
ls -l "$OUT/vmlinuz" "$OUT/initramfs.gz"
