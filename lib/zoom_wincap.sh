#!/bin/zsh
# capture the Zoom Meeting window every 3 s while the meeting runs; re-resolve the window id each minute
# and right after a failed capture. Window changes and failures go to $R/wincap.log, never /dev/null.
S=$1; R=$2; i=0; wid=""; alive=1; miss=0; mkdir -p $R/win
log() { print "$(date +%T) $*" >> $R/wincap.log }
while pgrep -q CptHost || (( alive )); do
  if (( i % 20 == 0 )) || [[ -z $wid || $wid == 0 ]]; then
    out=$(swift ${0:A:h}/zoom_window.swift 2>>$R/wincap.log); n=$(print -r -- $out | awk '/^BEST/{print $2}')
    # two misses in a row (~1 min apart) before calling it over: one odd window list must not end the recording
    m=$(print -r -- $out | awk '/^MEETING/{print $2}'); (( ${m:-0} )) && miss=0 || miss=$((miss+1)); (( miss < 2 )) && alive=1 || alive=0
    [[ $n != $wid ]] && log "window ${wid:-none} -> $n"; wid=$n
  fi
  if [[ -n $wid && $wid != 0 ]]; then
    f=$R/win/$(date +%H%M%S).jpg; screencapture -x -o -l$wid -t jpg $f 2>>$R/wincap.log
    [[ -s $f ]] || { log "capture failed on window $wid"; wid=""; }
  elif [[ $last != none ]]; then log "no meeting window"; fi
  [[ -n $wid && $wid != 0 ]] && last=$wid || last=none
  i=$((i+1)); sleep 3
done
log "meeting ended"
# no-OBS recordings (zoom_record.sh fallback) stop their audio recorders here
[[ -s $R/pids ]] && zsh ${0:A:h}/zoom_record.sh stop $R >> $R/wincap.log 2>&1
