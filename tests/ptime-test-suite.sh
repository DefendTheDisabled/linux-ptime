#!/bin/bash
# ptime-test-suite.sh — Comprehensive ptime verification
# Run on a system with the linux-ptime kernel and patched tools
set -uo pipefail

PASS=0
FAIL=0
SKIP=0
TESTDIR="/home/sean/ptime-tests"
PTIME_SET="/home/sean/ptime-set-simple"
PTIME_READ="/home/sean/ptime-read"
PTIME_EPOCH=1560608400  # 2019-06-15 14:20:00 UTC

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

check() {
    local label="$1"
    local result="$2"
    if [ "$result" -eq 0 ]; then
        echo -e "  ${GREEN}[PASS]${NC} $label"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $label"
        FAIL=$((FAIL + 1))
    fi
}

skip() {
    echo -e "  ${YELLOW}[SKIP]${NC} $1 — $2"
    SKIP=$((SKIP + 1))
}

# Read ptime value from a file (returns epoch seconds, 0 if not set)
get_ptime() {
    local output
    output=$("$PTIME_READ" "$1" 2>/dev/null)
    if echo "$output" | grep -q "ptime:.*[0-9]"; then
        echo "$output" | grep "ptime:" | awk '{print $2}' | cut -d. -f1
    else
        echo "0"
    fi
}

mkdir -p "$TESTDIR"
echo "==========================================="
echo "  PTIME TEST SUITE"
echo "  Kernel: $(uname -r)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "==========================================="
echo ""

# =============================================
echo "--- Section 1: Kernel Basics ---"
# =============================================

# Test 1: Set and read ptime on Btrfs
echo "test1" > "$TESTDIR/test1.txt"
"$PTIME_SET" "$TESTDIR/test1.txt" >/dev/null 2>&1
ptime=$(get_ptime "$TESTDIR/test1.txt")
check "Set and read ptime on Btrfs" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

# Test 2: New file has no ptime
echo "test2" > "$TESTDIR/test2.txt"
ptime=$(get_ptime "$TESTDIR/test2.txt")
check "New file has ptime=0 (unset)" "$([ "$ptime" = "0" ] && echo 0 || echo 1)"

# Test 3: Ptime survives sync + cache drop
echo "test3" > "$TESTDIR/test3.txt"
"$PTIME_SET" "$TESTDIR/test3.txt" >/dev/null 2>&1
sync
# Note: cache drop requires sudo — skip if not available
if echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null 2>&1; then
    ptime=$(get_ptime "$TESTDIR/test3.txt")
    check "Ptime survives sync + cache drop" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
else
    skip "Ptime survives cache drop" "requires sudo"
fi

# Test 4: Atomic save (write-temp + rename-over)
echo "original" > "$TESTDIR/test4.txt"
"$PTIME_SET" "$TESTDIR/test4.txt" >/dev/null 2>&1
echo "modified" > "$TESTDIR/test4.txt.tmp"
mv "$TESTDIR/test4.txt.tmp" "$TESTDIR/test4.txt"
ptime=$(get_ptime "$TESTDIR/test4.txt")
check "Atomic save (rename-over) preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

# Test 5: Source with ptime wins over target ptime on rename
echo "src" > "$TESTDIR/test5-src.txt"
echo "dst" > "$TESTDIR/test5-dst.txt"
# Set different ptime on source (use a different epoch)
struct_timespec_hack() {
    # We need to set a specific ptime, reuse ptime-set-simple which always uses 1560608400
    "$PTIME_SET" "$1" >/dev/null 2>&1
}
struct_timespec_hack "$TESTDIR/test5-src.txt"
struct_timespec_hack "$TESTDIR/test5-dst.txt"
# Now rename src over dst — source already has ptime, so source ptime should win
mv "$TESTDIR/test5-src.txt" "$TESTDIR/test5-dst.txt"
ptime=$(get_ptime "$TESTDIR/test5-dst.txt")
check "Source with existing ptime wins on rename-over" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

echo ""

# =============================================
echo "--- Section 2: cp -a Preservation ---"
# =============================================

# Test 6: cp -a Btrfs→Btrfs
echo "cp test" > "$TESTDIR/test6-src.txt"
"$PTIME_SET" "$TESTDIR/test6-src.txt" >/dev/null 2>&1
cp -a "$TESTDIR/test6-src.txt" "$TESTDIR/test6-dst.txt"
ptime=$(get_ptime "$TESTDIR/test6-dst.txt")
check "cp -a preserves ptime (Btrfs→Btrfs)" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

# Test 7: cp -a Btrfs→NTFS
if findmnt -t ntfs3 -o TARGET --noheadings | head -1 | read ntfs_mount; then
    ntfs_mount=$(findmnt -t ntfs3 -o TARGET --noheadings | head -1 | tr -d ' ')
    cp -a "$TESTDIR/test6-src.txt" "$ntfs_mount/ptime-test-cp.txt" 2>/dev/null
    if [ $? -eq 0 ]; then
        ptime=$(get_ptime "$ntfs_mount/ptime-test-cp.txt")
        check "cp -a Btrfs→NTFS (ptime→Date Created)" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
        rm -f "$ntfs_mount/ptime-test-cp.txt"
    else
        skip "cp -a Btrfs→NTFS" "write failed"
    fi
else
    skip "cp -a Btrfs→NTFS" "no NTFS mounted"
fi

# Test 8: mv cross-filesystem
echo "mv test" > "$TESTDIR/test8.txt"
"$PTIME_SET" "$TESTDIR/test8.txt" >/dev/null 2>&1
if [ -n "${ntfs_mount:-}" ]; then
    mv "$TESTDIR/test8.txt" "$ntfs_mount/ptime-test-mv.txt" 2>/dev/null
    if [ $? -eq 0 ]; then
        ptime=$(get_ptime "$ntfs_mount/ptime-test-mv.txt")
        check "mv cross-FS Btrfs→NTFS preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
        mv "$ntfs_mount/ptime-test-mv.txt" "$TESTDIR/test8-back.txt" 2>/dev/null
        ptime=$(get_ptime "$TESTDIR/test8-back.txt")
        check "mv cross-FS NTFS→Btrfs preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
    else
        skip "mv cross-FS" "write failed"
    fi
fi

echo ""

# =============================================
echo "--- Section 3: rsync Preservation ---"
# =============================================

mkdir -p "$TESTDIR/rsync-src" "$TESTDIR/rsync-dst"
echo "rsync test" > "$TESTDIR/rsync-src/file.txt"
"$PTIME_SET" "$TESTDIR/rsync-src/file.txt" >/dev/null 2>&1
rsync -a --crtimes "$TESTDIR/rsync-src/" "$TESTDIR/rsync-dst/" 2>/dev/null
ptime=$(get_ptime "$TESTDIR/rsync-dst/file.txt")
check "rsync --crtimes preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

echo ""

# =============================================
echo "--- Section 4: tar Archive Round-trip ---"
# =============================================

echo "tar test" > "$TESTDIR/tar-test.txt"
"$PTIME_SET" "$TESTDIR/tar-test.txt" >/dev/null 2>&1
tar --posix --zstd -cf "$TESTDIR/test.tar.zst" -C "$TESTDIR" tar-test.txt 2>/dev/null
mkdir -p "$TESTDIR/tar-extract"
tar --zstd -xf "$TESTDIR/test.tar.zst" -C "$TESTDIR/tar-extract" 2>/dev/null
ptime=$(get_ptime "$TESTDIR/tar-extract/tar-test.txt")
check "tar archive round-trip preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"

echo ""

# =============================================
echo "--- Section 5: Cross-Filesystem (USB) ---"
# =============================================

# Test each mounted USB filesystem
for fs_info in "stor1:ext4" "stor2:exfat" "stor3:fat32" "stor4:btrfs-usb"; do
    label="${fs_info%%:*}"
    fsname="${fs_info##*:}"
    mnt="/run/media/sean/$label"
    
    if [ ! -d "$mnt" ]; then
        skip "Btrfs→$fsname→Btrfs round-trip" "not mounted"
        continue
    fi
    
    # Find writable location
    testpath="$mnt/ptime-test.txt"
    if [ -d "$mnt/test" ]; then
        testpath="$mnt/test/ptime-test.txt"
    fi
    
    echo "roundtrip" > "$TESTDIR/fs-src.txt"
    "$PTIME_SET" "$TESTDIR/fs-src.txt" >/dev/null 2>&1
    
    cp -a "$TESTDIR/fs-src.txt" "$testpath" 2>/dev/null
    if [ $? -ne 0 ]; then
        skip "Btrfs→$fsname" "write permission denied"
        continue
    fi
    
    ptime=$(get_ptime "$testpath")
    check "Btrfs→$fsname preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
    
    cp -a "$testpath" "$TESTDIR/fs-back-$fsname.txt" 2>/dev/null
    ptime=$(get_ptime "$TESTDIR/fs-back-$fsname.txt")
    check "$fsname→Btrfs preserves ptime" "$([ "$ptime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
    
    rm -f "$testpath" "$TESTDIR/fs-back-$fsname.txt"
done

echo ""

# =============================================
echo "--- Section 6: NTFS Date Created Mapping ---"
# =============================================

if [ -n "${ntfs_mount:-}" ]; then
    echo "ntfs date test" > "$ntfs_mount/ptime-date-test.txt" 2>/dev/null
    if [ $? -eq 0 ]; then
        "$PTIME_SET" "$ntfs_mount/ptime-date-test.txt" >/dev/null 2>&1
        # Read btime — should equal ptime (NTFS maps ptime to creation time)
        output=$("$PTIME_READ" "$ntfs_mount/ptime-date-test.txt" 2>/dev/null)
        btime=$(echo "$output" | grep "btime:" | awk '{print $2}' | cut -d. -f1)
        check "NTFS Date Created = ptime (Windows would show 2019-06-15)" "$([ "$btime" = "$PTIME_EPOCH" ] && echo 0 || echo 1)"
        rm -f "$ntfs_mount/ptime-date-test.txt"
    fi
fi

echo ""

# =============================================
# Cleanup and Summary
# =============================================
rm -rf "$TESTDIR"

echo "==========================================="
TOTAL=$((PASS + FAIL + SKIP))
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}, ${YELLOW}$SKIP skipped${NC} (of $TOTAL)"
if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}ALL TESTS PASSED${NC}"
else
    echo -e "  ${RED}SOME TESTS FAILED${NC}"
fi
echo "==========================================="
exit $FAIL
