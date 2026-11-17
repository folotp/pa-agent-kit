# conf.awk: the one parser of harness.toml, for harness/dev and harness/gate.
#
# harness.toml is a restricted TOML subset: `key = "string"` or `key = ["a", "b"]` on one line,
# comments, blank lines, and the tables [checks] and [gate]. Prints one tab-separated record per
# setting:  conf <key> <value> | check <name> <command> | gate <key> <value>
# Arrays become space-separated words. Anything else is refused with its line number (exit 1), so
# that a typo cannot silently drop a check or a gate setting. Values may not contain double quotes
# or backslashes, and array items no commas. Types are checked here; values by their reader.
function bad(why) { printf "dev: harness.toml:%d: %s\n", NR, why > "/dev/stderr"; exit 1 }
/^[[:space:]]*(#.*)?$/ { next }
/^\[checks\]$/ { section = "checks"; next }
/^\[gate\]$/ { section = "gate"; next }
/^\[/ { bad("unsupported table") }
{
  if (!match($0, /^[a-z][a-z0-9_-]* = /)) bad("unsupported line")
  key = substr($0, 1, RLENGTH - 3)
  val = substr($0, RLENGTH + 1)
  if (val ~ /^"[^"\\]*"$/) {
    val = substr(val, 2, length(val) - 2)
    kind = "s"
  } else if (val ~ /^\[("[^"\\,]*"(, *"[^"\\,]*")*)?\]$/) {
    val = substr(val, 2, length(val) - 2)
    gsub(/"/, "", val)
    gsub(/, */, " ", val)
    kind = "a"
  } else bad("unsupported value")
  if (section == "checks") {
    if (kind != "s") bad("a check is a string")
    print "check\t" key "\t" val
  } else if (section == "gate") {
    if (!((kind == "s" && index(" repo merger verb release ci checks_app ", " " key " ")) ||
          (kind == "a" && index(" required guarded loaded keep_env ", " " key " "))))
      bad("unknown gate key, or wrong type: " key)
    print "gate\t" key "\t" val
  } else {
    if (!((key == "profile" && kind == "s") || (key == "tools" && kind == "a"))) bad("unknown key " key)
    print "conf\t" key "\t" val
  }
}
