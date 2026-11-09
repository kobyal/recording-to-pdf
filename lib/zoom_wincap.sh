#!/bin/zsh
# capture the Zoom Meeting window every 3 s while the meeting runs; re-resolve the window id each minute
# and right after a failed capture. Window changes and failures go to $R/wincap.log, never /dev/null.
S=$1; R=$2; i=0; wid=""; alive=1; mkdir -p $R/win
log() { print "$(date +%T) $*" >> $R/wincap.log }
while pgrep -q CptHost || (( alive )); do
  if (( i % 20 == 0 )) || [[ -z $wid || $wid == 0 ]]; then
    out=$(swift ${0:A:h}/zoom_window.swift 2>>$R/wincap.log); n=$(print -r -- $out | awk '/^BEST/{print $2}')
    alive=$(print -r -- $out | awk '/^MEETING/{print $2}'); alive=${alive:-0}
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
