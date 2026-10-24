import CoreGraphics
// on-screen layer-0 windows only: Zoom parks unnamed helper windows off-display, and capturing one yields nothing.
// rank by title: "Zoom Meeting" > "Zoom" (the meeting window while viewing a share) > untitled; skip "Zoom Workplace" etc.
let l = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as! [[String:Any]]
func rank(_ n: String) -> Int { n.contains("Meeting") ? 3 : n == "Zoom" ? 2 : n == "" ? 1 : 0 }
var best = (0, 0, 0.0)
for w in l where (w["kCGWindowOwnerName"] as? String ?? "") == "zoom.us" || (w["kCGWindowOwnerName"] as? String ?? "") == "Zoom" {
  let b = w["kCGWindowBounds"] as! [String:Any]; let a = (b["Width"] as! Double) * (b["Height"] as! Double)
  let name = w["kCGWindowName"] as? String ?? ""; let r = rank(name); let on = w["kCGWindowIsOnscreen"] as? Bool ?? false
  if (w["kCGWindowLayer"] as? Int ?? 1) == 0 && on && a > 60000 && r > 0 && (r > best.1 || (r == best.1 && a > best.2)) { best = (w["kCGWindowNumber"] as! Int, r, a) }
  print(w["kCGWindowNumber"]!, name, b["Width"]!, b["Height"]!, w["kCGWindowLayer"]!, on ? "on" : "off")
}
print("BEST", best.0)
