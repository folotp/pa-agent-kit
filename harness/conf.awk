# conf.awk: the one parser of harness.toml, for harness/dev and harness/gate.
#
# harness.toml is a restricted TOML subset: `key = "string"` or `key = ["a", "b"]` on one line,
# comments, blank lines, and the tables [checks], [verbs] and [gate]. Prints one tab-separated record
# per setting:  conf <key> <value> | check <name> <command> | verb <name> <command> | gate <key> <value>
# Arrays become space-separated words, so an array item may not be blank or contain whitespace (it
# would vanish or become several items). Anything else is refused with its line number (exit 1),
# so that a typo cannot silently drop a check or a gate setting: a key given twice in one table, a
# blank or whitespace-only string. Values may not contain double quotes or backslashes, and array
# items no commas. Types are checked here; values by their reader.
function bad(why) { printf "dev: harness.toml:%d: %s\n", NR, why > "/dev/stderr"; exit 1 }
/^[[:space:]]*(#.*)?$/ { next }
/^\[checks\]$/ { section = "checks"; next }
/^\[verbs\]$/ { section = "verbs"; next }
/^\[gate\]$/ { section = "gate"; next }
/^\[/ { bad("unsupported table") }
{
  if (!match($0, /^[a-z][a-z0-9_-]* = /)) bad("unsupported line")
  key = substr($0, 1, RLENGTH - 3)
  val = substr($0, RLENGTH + 1)
  if ((section SUBSEP key) in seen) bad("key given twice: " key)
  seen[section SUBSEP key] = 1
  if (val ~ /^"[^"\\]*"$/) {
    val = substr(val, 2, length(val) - 2)
    if (val !~ /[^[:space:]]/) bad("blank value: " key)
    kind = "s"
  } else if (val ~ /^\[("[^"\\,]*"(, *"[^"\\,]*")*)?\]$/) {
    val = substr(val, 2, length(val) - 2)
    n = split(val, items, /, */)
    for (i = 1; i <= n; i++) {
      item = substr(items[i], 2, length(items[i]) - 2)
      if (item == "" || item ~ /[[:space:]]/) bad("blank array item, or whitespace in one: " key)
    }
    gsub(/"/, "", val)
    gsub(/, */, " ", val)
    kind = "a"
  } else bad("unsupported value")
  if (section == "checks") {
    if (kind != "s") bad("a check is a string")
    print "check\t" key "\t" val
  } else if (section == "verbs") {
    if (kind != "s") bad("a verb is a string")
    if (index(" setup check ci gate apply deploy x ", " " key " ")) bad("verb name is reserved: " key)
    print "verb\t" key "\t" val
  } else if (section == "gate") {
    if (!((kind == "s" && index(" repo merger verb release ci checks_app ", " " key " ")) ||
          (kind == "a" && index(" required guarded loaded keep_env ", " " key " "))))
      bad("unknown gate key, or wrong type: " key)
    print "gate\t" key "\t" val
  } else {
    # protected_branches: standing branches that harness/git-prune-merged.sh never deletes (besides
    # main and master), read by that script only.
    if (!(((key == "profile" || key == "check") && kind == "s") ||
          ((key == "tools" || key == "protected_branches") && kind == "a"))) bad("unknown key, or wrong type: " key)
    print "conf\t" key "\t" val
  }
}
