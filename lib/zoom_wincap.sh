#!/bin/zsh
# capture the Zoom Meeting window every 3 s while the meeting runs; re-resolve the window id each minute
# and right after a failed capture. Window changes and failures go to $R/wincap.log, never /dev/null.
S=$1; R=$2; i=0; wid=""; mkdir -p $R/win
log() { print "$(date +%T) $*" >> $R/wincap.log }
while pgrep -q CptHost; do
  if (( i % 20 == 0 )) || [[ -z $wid ]]; then
    n=$(swift ${0:A:h}/zoom_window.swift 2>>$R/wincap.log | awk '/^BEST/{print $2}')
    [[ $n != $wid ]] && log "window ${wid:-none} -> $n"; wid=$n
  fi
  if [[ -n $wid && $wid != 0 ]]; then
    f=$R/win/$(date +%H%M%S).jpg; screencapture -x -o -l$wid -t jpg $f 2>>$R/wincap.log
    [[ -s $f ]] || { log "capture failed on window $wid"; wid=""; }
  else log "no meeting window"; fi
  i=$((i+1)); sleep 3
done
log "meeting ended"
