import CoreGraphics
// layer-0 windows that lie on a display: Zoom parks unnamed helper windows off-display, and capturing one yields nothing.
// Not kCGWindowIsOnscreen: that is false for a window on another Space (Zoom in full screen while the user works
// elsewhere), and screencapture -l still captures those.
// layer 3, not 0: the meeting window floats there while the user shares their own screen.
// MEETING 1 when a "Zoom Meeting" window, a large window titled just "Zoom" (viewing a share) or the floating video exists: newer Zoom builds run no CptHost process.
// rank by title: "Zoom Meeting" > "Zoom" (the meeting window while viewing a share) > untitled; skip "Zoom Workplace" etc.
let l = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as! [[String:Any]]
func rank(_ n: String) -> Int { n.contains("Meeting") ? 3 : n == "Zoom" ? 2 : n == "" ? 1 : 0 }
var best = (0, 0, 0.0); var meeting = false
for w in l where (w["kCGWindowOwnerName"] as? String ?? "") == "zoom.us" || (w["kCGWindowOwnerName"] as? String ?? "") == "Zoom" {
  let b = w["kCGWindowBounds"] as! [String:Any]; let a = (b["Width"] as! Double) * (b["Height"] as! Double)
  let name = w["kCGWindowName"] as? String ?? ""; let r = rank(name)
  let bw = b["Width"] as! Double
  if name == "Zoom Meeting" || name.contains("floating video") || (name == "Zoom" && bw > 600) { meeting = true }
  var rect = CGRect.zero; var nd: UInt32 = 0
  CGRectMakeWithDictionaryRepresentation(b as CFDictionary, &rect); CGGetDisplaysWithRect(rect, 0, nil, &nd); let on = nd > 0
  if (w["kCGWindowLayer"] as? Int ?? 9) <= 3 && on && a > 60000 && r > 0 && (r > best.1 || (r == best.1 && a > best.2)) { best = (w["kCGWindowNumber"] as! Int, r, a) }
  print(w["kCGWindowNumber"]!, name, b["Width"]!, b["Height"]!, w["kCGWindowLayer"]!, on ? "on" : "off")
}
print("BEST", best.0)
print("MEETING", meeting ? 1 : 0)
