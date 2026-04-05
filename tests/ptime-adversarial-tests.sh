#!/bin/bash
# ptime-adversarial-tests.sh — 10 adversarial test sequences from GPT
set -uo pipefail

PTIME_SET="/home/sean/ptime-set-simple"
PTIME_READ="/home/sean/ptime-read"
LAB="/home/sean/ptime-adversarial"
NTFS="$(findmnt -rn -t ntfs3 -o TARGET | head -n1 || true)"
PASS=0; FAIL=0

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

get_ptime_sec() {
    local out
    out=$("$PTIME_READ" "$1" 2>/dev/null)
    if echo "$out" | grep -q "ptime:.*[1-9]"; then
        echo "$out" | grep "ptime:" | awk '{print $2}' | cut -d. -f1
    else
        echo "0"
    fi
}

check() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        echo -e "  ${GREEN}[PASS]${NC} $label (got $actual)"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} $label (expected $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

rm -rf "$LAB"
mkdir -p "$LAB"

echo "========================================="
echo "  PTIME ADVERSARIAL TESTS"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "========================================="
echo ""

# TEST 1: Double rename attack
echo "--- Test 1: Double rename attack ---"
mkdir -p "$LAB/t1"
echo A > "$LAB/t1/A"; echo B > "$LAB/t1/B"; echo D > "$LAB/t1/D"
"$PTIME_SET" "$LAB/t1/A" >/dev/null 2>&1   # ptime=1560608400
"$PTIME_SET" "$LAB/t1/B" >/dev/null 2>&1
mv -f "$LAB/t1/A" "$LAB/t1/B"              # A (has ptime) over B (has ptime) — source wins
p=$(get_ptime_sec "$LAB/t1/B")
check "A(ptime) renamed over B(ptime) — source ptime wins" "1560608400" "$p"
mv -f "$LAB/t1/D" "$LAB/t1/B"              # D (no ptime) over B (has ptime) — inherit
p=$(get_ptime_sec "$LAB/t1/B")
check "D(no ptime) over B(ptime) — inherits B ptime" "1560608400" "$p"
echo ""

# TEST 2: Rapid chmod storm
echo "--- Test 2: Rapid chmod storm ---"
mkdir -p "$LAB/t2"
echo x > "$LAB/t2/file"; chmod 600 "$LAB/t2/file"
"$PTIME_SET" "$LAB/t2/file" >/dev/null 2>&1
chmod 644 "$LAB/t2/file" && chmod 755 "$LAB/t2/file" && chmod 644 "$LAB/t2/file"
p=$(get_ptime_sec "$LAB/t2/file")
check "ptime survives chmod storm" "1560608400" "$p"
echo ""

# TEST 3: Truncate attack
echo "--- Test 3: Truncate attack ---"
mkdir -p "$LAB/t3"
echo abcdef > "$LAB/t3/file"
"$PTIME_SET" "$LAB/t3/file" >/dev/null 2>&1
truncate -s 0 "$LAB/t3/file"
p=$(get_ptime_sec "$LAB/t3/file")
check "ptime survives truncate" "1560608400" "$p"
echo ""

# TEST 4: Hardlink rename confusion
echo "--- Test 4: Hardlink rename confusion ---"
mkdir -p "$LAB/t4"
echo orig > "$LAB/t4/orig"
ln "$LAB/t4/orig" "$LAB/t4/link"
"$PTIME_SET" "$LAB/t4/orig" >/dev/null 2>&1
echo new > "$LAB/t4/newfile"
mv -f "$LAB/t4/newfile" "$LAB/t4/link"     # newfile over hardlink
p=$(get_ptime_sec "$LAB/t4/orig")
check "orig keeps ptime after hardlink overwritten" "1560608400" "$p"
echo ""

# TEST 5: Concurrent copy
echo "--- Test 5: Concurrent copy ---"
mkdir -p "$LAB/t5"
echo copy > "$LAB/t5/file"
"$PTIME_SET" "$LAB/t5/file" >/dev/null 2>&1
cp -a "$LAB/t5/file" "$LAB/t5/dest1" &
cp -a "$LAB/t5/file" "$LAB/t5/dest2" &
wait
p1=$(get_ptime_sec "$LAB/t5/dest1")
p2=$(get_ptime_sec "$LAB/t5/dest2")
check "concurrent cp dest1 has ptime" "1560608400" "$p1"
check "concurrent cp dest2 has ptime" "1560608400" "$p2"
echo ""

# TEST 6: mv to tmpfs and back (EXPECTED LOSS)
echo "--- Test 6: mv to tmpfs and back (EXPECTED PTIME LOSS) ---"
mkdir -p "$LAB/t6" /dev/shm/ptime-t6
echo tmpfs > "$LAB/t6/file"
"$PTIME_SET" "$LAB/t6/file" >/dev/null 2>&1
mv "$LAB/t6/file" /dev/shm/ptime-t6/file
p_tmpfs=$(get_ptime_sec /dev/shm/ptime-t6/file)
mv /dev/shm/ptime-t6/file "$LAB/t6/file.back"
p_back=$(get_ptime_sec "$LAB/t6/file.back")
check "ptime LOST on tmpfs (expected)" "0" "$p_tmpfs"
check "ptime LOST after tmpfs round-trip (expected)" "0" "$p_back"
rm -rf /dev/shm/ptime-t6
echo ""

# TEST 7: tar through pipe to Btrfs
echo "--- Test 7: tar through pipe ---"
mkdir -p "$LAB/t7" "$LAB/t7/out"
echo tar > "$LAB/t7/file"
"$PTIME_SET" "$LAB/t7/file" >/dev/null 2>&1
tar --posix -cf - -C "$LAB/t7" file | tar -xf - -C "$LAB/t7/out"
p=$(get_ptime_sec "$LAB/t7/out/file")
check "tar pipe to Btrfs preserves ptime" "1560608400" "$p"
echo ""

# TEST 8: touch after ptime
echo "--- Test 8: touch after ptime ---"
mkdir -p "$LAB/t8"
echo touch > "$LAB/t8/file"
"$PTIME_SET" "$LAB/t8/file" >/dev/null 2>&1
touch "$LAB/t8/file"
p=$(get_ptime_sec "$LAB/t8/file")
check "ptime survives touch" "1560608400" "$p"
echo ""

# TEST 9: Overwrite via redirect
echo "--- Test 9: Overwrite via redirect ---"
mkdir -p "$LAB/t9"
echo old > "$LAB/t9/file"
"$PTIME_SET" "$LAB/t9/file" >/dev/null 2>&1
echo "new content" > "$LAB/t9/file"
p=$(get_ptime_sec "$LAB/t9/file")
check "ptime survives redirect overwrite" "1560608400" "$p"
echo ""

# TEST 10: NTFS round-trip with chmod
echo "--- Test 10: NTFS round-trip with chmod ---"
if [ -n "$NTFS" ]; then
    mkdir -p "$LAB/t10"
    echo ntfs > "$LAB/t10/file"
    "$PTIME_SET" "$LAB/t10/file" >/dev/null 2>&1
    cp -a "$LAB/t10/file" "$NTFS/ptime-adv-test.txt"
    p_ntfs=$(get_ptime_sec "$NTFS/ptime-adv-test.txt")
    check "Btrfs→NTFS ptime" "1560608400" "$p_ntfs"
    chmod 600 "$NTFS/ptime-adv-test.txt" 2>/dev/null
    p_after=$(get_ptime_sec "$NTFS/ptime-adv-test.txt")
    check "NTFS ptime survives chmod" "1560608400" "$p_after"
    cp -a "$NTFS/ptime-adv-test.txt" "$LAB/t10/back.txt"
    p_back=$(get_ptime_sec "$LAB/t10/back.txt")
    check "NTFS→Btrfs ptime after chmod" "1560608400" "$p_back"
    rm -f "$NTFS/ptime-adv-test.txt"
else
    echo -e "  ${YELLOW}[SKIP]${NC} No NTFS mounted"
fi
echo ""

# Cleanup
rm -rf "$LAB"

echo "========================================="
TOTAL=$((PASS + FAIL))
echo -e "  Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC} (of $TOTAL)"
if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}ALL ADVERSARIAL TESTS PASSED${NC}"
fi
echo "========================================="
exit $FAIL
