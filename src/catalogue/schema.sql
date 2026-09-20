-- Lin Wallpapers catalogue, schema version 1 (M1 contract §2.4).
-- FROZEN once released: later changes are new migrations, never edits to this file.
-- Executed statement by statement inside the migration's transaction (see migrations/m0001_initial.py).

CREATE TABLE setting(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE volume(
  volume_id TEXT PRIMARY KEY, label TEXT, fstype TEXT, last_mount TEXT,
  removable INTEGER NOT NULL DEFAULT 0, network INTEGER NOT NULL DEFAULT 0,
  stable_inodes INTEGER NOT NULL DEFAULT 1,
  scan_answer TEXT CHECK (scan_answer IN ('yes','no')),
  online INTEGER NOT NULL DEFAULT 0, last_seen INTEGER
) WITHOUT ROWID;

CREATE TABLE root(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('xdg','system','volume','user')),
  enabled INTEGER NOT NULL DEFAULT 1, volume_id TEXT, last_scan INTEGER, last_scan_id INTEGER
);

-- key: stable id of a builtin group, NULL for user groups
CREATE TABLE exclusion_group(
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, name TEXT NOT NULL UNIQUE,
  builtin INTEGER NOT NULL DEFAULT 0, locked INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE exclusion(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('folder','file','pattern')), value TEXT NOT NULL,
  volume_id TEXT, device INTEGER, inode INTEGER,
  root_id INTEGER REFERENCES root(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES exclusion_group(id) ON DELETE SET NULL,
  builtin INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, created INTEGER, note TEXT
);

-- NULLs are distinct in UNIQUE(), hence the expression index
CREATE UNIQUE INDEX exclusion_identity ON exclusion(kind, value, ifnull(volume_id,''), ifnull(root_id,0));

-- width/height are AFTER EXIF rotation; score/badges/palette/dhash stay NULL until M2
CREATE TABLE image(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, dir TEXT NOT NULL, name TEXT NOT NULL,
  root_id INTEGER REFERENCES root(id) ON DELETE SET NULL, volume_id TEXT,
  device INTEGER, inode INTEGER, mtime_ns INTEGER, size INTEGER,
  width INTEGER, height INTEGER,
  exif_orientation INTEGER, format TEXT, has_alpha INTEGER NOT NULL DEFAULT 0,
  is_animated INTEGER NOT NULL DEFAULT 0, has_icc INTEGER NOT NULL DEFAULT 0, aspect REAL, megapixels REAL,
  probe_status TEXT NOT NULL DEFAULT 'ok'
    CHECK (probe_status IN ('ok','truncated','zero_byte','unsupported','over_budget','too_large','error')),
  probe_error TEXT,
  score INTEGER, badges TEXT, palette TEXT, dhash INTEGER,
  thumb_key TEXT, thumb_status TEXT CHECK (thumb_status IN ('ok','failed','too_large')),
  first_seen INTEGER, last_seen INTEGER, seen_scan INTEGER, missing INTEGER NOT NULL DEFAULT 0,
  excluded_by INTEGER REFERENCES exclusion(id) ON DELETE SET NULL
);

CREATE INDEX image_inode ON image(device, inode);
CREATE INDEX image_dir ON image(dir);
CREATE INDEX image_volume ON image(volume_id);
CREATE INDEX image_root ON image(root_id, seen_scan);
CREATE INDEX image_name ON image(name COLLATE NOCASE);
CREATE INDEX image_first_seen ON image(first_seen);
CREATE INDEX image_size ON image(size);
CREATE INDEX image_mp ON image(megapixels);
CREATE INDEX image_excluded ON image(excluded_by) WHERE excluded_by IS NOT NULL;

-- width/height: physical pixels after rotation. connected = 1 marks the CURRENT target set (detected and
-- declared alike); the bound keeps the integer crop arithmetic far from 64-bit overflow.
CREATE TABLE display(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  width INTEGER NOT NULL CHECK (width BETWEEN 1 AND 1000000),
  height INTEGER NOT NULL CHECK (height BETWEEN 1 AND 1000000),
  scale REAL NOT NULL DEFAULT 1.0, is_primary INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK (source IN ('gdk','drm','xrandr','declared')),
  connected INTEGER NOT NULL DEFAULT 1, first_seen INTEGER, last_seen INTEGER, UNIQUE(name, width, height)
);

-- issues: JSON {issue kind: count}; reason: e.g. DISPLAY_NOT_DETECTED + evidence JSON
CREATE TABLE scan(
  id INTEGER PRIMARY KEY, started INTEGER NOT NULL, finished INTEGER, pid INTEGER, root_ids TEXT, display_set TEXT,
  threshold_pct INTEGER, found INTEGER DEFAULT 0, probed INTEGER DEFAULT 0, unchanged INTEGER DEFAULT 0,
  ideal INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, issues TEXT, reason TEXT,
  result TEXT NOT NULL DEFAULT 'running' CHECK (result IN ('running','ok','cancelled','interrupted','error'))
);

CREATE TABLE scan_skip(
  scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE, rule_id INTEGER NOT NULL,
  dirs INTEGER NOT NULL DEFAULT 0, files INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scan_id, rule_id)
) WITHOUT ROWID;

-- first 500 per kind per scan; totals live in scan.issues
CREATE TABLE scan_issue(
  id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, path TEXT NOT NULL, detail TEXT
);

-- derived data: one row per (image, target display) that is ideal or a near miss; rebuilt by ideal.rebuild()
CREATE TABLE ideal_image(
  image_id INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
  display_id INTEGER NOT NULL REFERENCES display(id) ON DELETE CASCADE,
  verdict TEXT NOT NULL CHECK (verdict IN ('ideal','near')), exact INTEGER NOT NULL,
  crop_loss REAL NOT NULL, coverage REAL NOT NULL,
  PRIMARY KEY (image_id, display_id)
) WITHOUT ROWID;

CREATE INDEX ideal_by_display ON ideal_image(display_id, verdict);

-- manual corrections; survive rebuilds, rescans and display changes
CREATE TABLE ideal_pin(
  image_id INTEGER PRIMARY KEY REFERENCES image(id) ON DELETE CASCADE,
  pinned TEXT NOT NULL CHECK (pinned IN ('in','out'))
);
