PRAGMA synchronous = OFF;
PRAGMA journal_mode = OFF;
PRAGMA locking_mode = EXCLUSIVE;
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS "Folder" (
	id INTEGER PRIMARY KEY,
	"name" TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS "Address" (
	id INTEGER PRIMARY KEY,
	"address" TEXT UNIQUE NOT NULL COLLATE NOCASE,
	"name" TEXT
);

CREATE TABLE IF NOT EXISTS "Message" (
	id INTEGER PRIMARY KEY,
	"folder" INTEGER REFERENCES Folder (id),
	"filename" TEXT,
	"size" INTEGER,
	"messageid" TEXT UNIQUE,
	"from" INTEGER REFERENCES Address (id),
	"replyto" INTEGER REFERENCES Address (id),
	"subject" TEXT,
	"text" TEXT,
	"parent" INTEGER REFERENCES Message (id),
	"date" DATETIME,
	"received" DATETIME
);

CREATE TABLE IF NOT EXISTS "To" (
	"message" INTEGER NOT NULL REFERENCES Message (id),
	"address" INTEGER NOT NULL REFERENCES Address (id),
	"cc" INTEGER NOT NULL,
	PRIMARY KEY ("message","address")
);
