#!/bin/zsh
# record a live Zoom meeting in one command (macOS): new folder, OBS audio + Zoom-app video backup, window frames.
#   zoom_record.sh start [--lang he] [--root ~/Documents/r2r-work]   # run once you are in the meeting
#   zoom_record.sh check [rec_dir]                                   # health check; default: the latest recording
# OBS needs Screen Recording + Microphone permission; the shell running this needs Screen Recording.
H=${0:A:h}; PY=${H:h}/.venv/bin/python; O=~/Library/Application\ Support/obs-studio
cmd=${1:-start}; shift; lang=""; root=~/Documents/r2r-work
while (( $# )); do case $1 in --lang) lang=$2; shift 2;; --root) root=$2; shift 2;; *) R=$1; shift;; esac; done

obs_config() {  # OBS overwrites its config on exit, so only call this with OBS closed
  local uuid=$(swift -e 'import ApplicationServices; print(CFUUIDCreateString(nil, CGDisplayCreateUUIDFromDisplayID(CGMainDisplayID())!.takeRetainedValue())!)' 2>/dev/null)
  mkdir -p "$O/basic/profiles/R2R" "$O/basic/scenes"
  for f in global.ini user.ini; do [[ -s "$O/$f" ]] || print "[General]\nFirstRun=true\nLastVersion=537001986\nEnableAutoUpdates=false" > "$O/$f"
    grep -q '^\[Basic\]' "$O/$f" || print "\n[Basic]\nProfile=R2R\nProfileDir=R2R\nSceneCollection=R2R\nSceneCollectionFile=R2R\nConfigOnNewProfile=false" >> "$O/$f"; done
  cat > "$O/basic/profiles/R2R/basic.ini" <<EOF
[General]
Name=R2R

[Output]
Mode=Simple

[SimpleOutput]
FilePath=$R
RecFormat2=fragmented_mp4
RecQuality=Small
RecEncoder=apple_h264
RecAudioEncoder=aac
ABitrate=160
FileNameWithoutSpace=true

[Video]
BaseCX=1920
BaseCY=1080
OutputCX=1920
OutputCY=1080
FPSType=1
FPSInt=5

[Audio]
SampleRate=48000
ChannelSetup=Stereo
EOF
  # Zoom app audio (others) + default mic (you: Zoom's output never contains your own voice) + Zoom app video, fitted to 1080p
  cat > "$O/basic/scenes/R2R.json" <<EOF
{"name": "R2R", "current_scene": "Zoom", "current_program_scene": "Zoom", "scene_order": [{"name": "Zoom"}],
 "sources": [
  {"id": "scene", "versioned_id": "scene", "name": "Zoom", "uuid": "11111111-1111-4111-8111-111111111111",
   "settings": {"id_counter": 3, "items": [
     {"name": "Zoom video", "source_uuid": "44444444-4444-4444-8444-444444444444", "visible": true, "id": 3,
      "bounds_type": 2, "bounds": {"x": 1920.0, "y": 1080.0}, "bounds_align": 0, "pos": {"x": 0.0, "y": 0.0}},
     {"name": "Zoom audio", "source_uuid": "22222222-2222-4222-8222-222222222222", "visible": true, "id": 1},
     {"name": "Mic", "source_uuid": "33333333-3333-4333-8333-333333333333", "visible": true, "id": 2}]}},
  {"id": "screen_capture", "versioned_id": "screen_capture", "name": "Zoom video", "uuid": "44444444-4444-4444-8444-444444444444",
   "settings": {"type": 2, "application": "us.zoom.xos", "display_uuid": "$uuid", "show_cursor": false, "hide_obs": true}},
  {"id": "sck_audio_capture", "versioned_id": "sck_audio_capture", "name": "Zoom audio", "uuid": "22222222-2222-4222-8222-222222222222",
   "settings": {"type": 1, "application": "us.zoom.xos"}},
  {"id": "coreaudio_input_capture", "versioned_id": "coreaudio_input_capture", "name": "Mic", "uuid": "33333333-3333-4333-8333-333333333333",
   "settings": {"device_id": "default"}}]}
EOF
}

check() {  # frames growing, OBS recording, audio not silent and actually speech
  local ok=1 rec=$(ls -t $R/*.mp4(N) 2>/dev/null | head -1) n=$(ls $R/win 2>/dev/null | wc -l | tr -d ' ')
  local last=$(ls -t $R/win 2>/dev/null | head -1); local age=$(( $(date +%s) - $(stat -f %m $R/win/$last 2>/dev/null || echo 0) ))
  print "folder:  $R"
  if pgrep -q -f zoom_wincap.sh && (( age < 15 )); then print "frames:  OK  $n saved, last ${age}s ago"
  else local since="none yet"; (( n )) && since="last ${age}s ago"; print "frames:  FAIL  $n saved, $since, capture loop $(pgrep -q -f zoom_wincap.sh && echo running || echo stopped)"; ok=0
    tail -3 $R/wincap.log 2>/dev/null | sed 's/^/         /'; fi
  if ! pgrep -q -x OBS; then print "obs:     FAIL  not running"; ok=0
  elif [[ -z $rec ]]; then print "obs:     FAIL  running but no recording in $R"; ok=0
  else
    local dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $rec 2>/dev/null | cut -d. -f1)
    print "obs:     OK  ${rec:t}, ${dur:-?}s"
    local w=$R/scratch/probe.wav; mkdir -p $R/scratch
    ffmpeg -v quiet -sseof -30 -i $rec -vn -ac 1 -ar 16000 -y $w 2>/dev/null
    local mean=$(ffmpeg -i $w -af volumedetect -f null - 2>&1 | awk '/mean_volume/{print $5}')
    local model=mlx-community/whisper-large-v3-turbo; [[ $lang == he ]] && model=mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx
    local text=$($PY -c "import sys,mlx_whisper;r=mlx_whisper.transcribe(sys.argv[1],path_or_hf_repo=sys.argv[2],language=sys.argv[3] or None,condition_on_previous_text=False);print(r['text'].strip())" $w $model "$lang" 2>/dev/null | tail -1)
    local words=$(print -r -- $text | wc -w | tr -d ' ')
    if [[ -z $mean ]] || (( ${mean%.*} < -38 )) || (( words < 8 )); then
      print "audio:   FAIL?  mean ${mean:-?} dB, $words words in the last 30 s (silence or nobody talking?)"; ok=0
    else print "audio:   OK  mean $mean dB, $words words"; fi
    print "heard:   \"${text[1,160]}\""
  fi
  (( ok )) && print "HEALTH OK" || print "HEALTH PROBLEM"
}

if [[ $cmd == check ]]; then R=${R:-$(cat $root/CURRENT 2>/dev/null)}; [[ -d $R ]] || { print "no recording folder"; exit 1 }; check; exit; fi
[[ $cmd == start ]] || { print "usage: zoom_record.sh start|check"; exit 2 }

pgrep -q CptHost || { print "No Zoom meeting running (CptHost). Join the meeting first."; exit 1 }
R=$root/zoom-$(date +%Y%m%d-%H%M); mkdir -p $R/win $R/scratch; print $R > $root/CURRENT
if pgrep -q -x OBS; then osascript -e 'quit app "OBS"' 2>/dev/null; for i in {1..10}; do pgrep -q -x OBS || break; sleep 1; done; pkill -x OBS; sleep 1; fi
rm -rf "$O/.sentinel"; obs_config
open -a OBS --args --profile R2R --collection R2R --startrecording --minimize-to-tray
nohup zsh $H/zoom_wincap.sh $R/scratch $R > /dev/null 2>&1 &
print "recording into $R; checking in 35 s..."
sleep 35; check
