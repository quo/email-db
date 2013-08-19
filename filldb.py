#!/usr/bin/python3

import os, re, sqlite3, email, email.utils, email.header, email.feedparser, datetime, collections
import util

def decode_payload(msg):
	charset = msg.get_charset()
	text = msg.get_payload(decode=True).decode(charset.input_codec if charset else 'iso-8859-1', 'replace')
	if msg.get_content_type() == 'text/html':
		for tag in ('head', 'style', 'blockquote'):
			text = re.sub('(?i)<'+tag+'[^>]*>.*?</'+tag+'>', ' ', text)
		text = util.decode_entities(re.sub('<[^>]*>', ' ', text))
	return text
def get_text_payload(msg, type):
	if msg.is_multipart():
		for m in msg.get_payload():
			p = get_text_payload(m, type)
			if p: return p
	elif msg.get_content_type() == type:
		return decode_payload(msg)
def get_payload(msg):
	if not msg.is_multipart(): return decode_payload(msg)
	return get_text_payload(msg, 'text/plain') or get_text_payload(msg, 'text/html')
def get_summary(text):
	lines = []
	for s in text.split('\n'):
		if s:
			if re.search(r'^(_{5}|-{5}|%{5}|From: |Date: |Subject: )|<[^@>]+@[^@>]+>', s): break
			if s[0] not in '>|':
				lines.append(s)
	return re.sub('\\s+', ' ', '\n'.join(lines)).strip()[:1024]

def decode_single(s, enc):
	if isinstance(s, str):
		if enc: raise ValueError('string with encoding', s, enc)
		return s
	if not enc or enc == 'unknown-8bit': enc = 'iso-8859-1'
	return s.decode(enc)
def decode_and_normalize(header):
	return re.sub('\s+', ' ', ' '.join(decode_single(s, enc) for s, enc in email.header.decode_header(header))).strip()

def get_message(sql, messageid):
	if messageid is None: return None
	messageid = re.sub('[\s,]+', '', messageid)
	if '@' in messageid:
		local, domain = messageid.split('@', 1)
		messageid = local + '@' + domain.lower()
	res = tuple(sql.execute('SELECT id FROM Message WHERE messageid=?', (messageid,)))
	if res:
		(i,), = res
		return i
	return sql.execute('INSERT INTO Message (messageid) VALUES (?)', (messageid,)).lastrowid

def get_address(sql, address):
	if address is None: return None
	res = tuple(sql.execute('SELECT id FROM Address WHERE address=?', (address,)))
	if res:
		(i,), = res
		return i
	return sql.execute('INSERT INTO Address (address) VALUES (?)', (address,)).lastrowid

def get_date(s, log):
	# FIXME time zones
	if s is not None:
		d = email.utils.parsedate(s)
		if d is not None:
			try:
				return datetime.datetime(*d[:6])
			except ValueError:
				pass # out-of-range date
		log('Invalid date: %r', s)

def insert_message(sql, folderid, dirpath, filename, names, log):
	f = os.path.join(dirpath, filename)
	parser = email.feedparser.BytesFeedParser()
	parser.feed(open(f, 'rb').read())
	msg = parser.close()
	#msg = email.message_from_file(open(f, 'rb'))
	if msg.defects:
		log('defects in %r: %r', f, msg.defects)

	messageid = msg['message-id']
	if messageid is not None:
		messageid = re.findall('<[^>]*>', messageid)
		messageid = messageid[0] if messageid else None
	if messageid is None:
		row = sql.execute('INSERT INTO Message DEFAULT VALUES').lastrowid
	else:
		while True:
			row = get_message(sql, messageid)
			(prevfilename,), = tuple(sql.execute('SELECT filename FROM Message WHERE id=?', (row,)))
			if prevfilename is None: break
			log('Duplicate message ID: %r and %r', f, prevfilename)
			messageid += '*'

	fromaddr = msg['from']
	if fromaddr is not None:
		realname, fromaddr = email.utils.parseaddr(fromaddr)
		realname = decode_and_normalize(realname)
		fromaddr = get_address(sql, fromaddr)
		if realname: names.setdefault(fromaddr, collections.Counter())[realname] += 10
	replytoaddr = msg['reply-to']
	if replytoaddr is not None:
		realname, replytoaddr = email.utils.parseaddr(replytoaddr)
		realname = decode_and_normalize(realname)
		replytoaddr = get_address(sql, replytoaddr)
		if realname: names.setdefault(replytoaddr, collections.Counter())[realname] += 10
	else: replytoaddr = fromaddr

	subject = msg['subject']
	if subject is not None:
		subject = decode_and_normalize(subject)

	date = get_date(msg['date'], log)

	received = msg.get_all('received', [None])[0]
	if received is not None:
		received = get_date(received.split(';')[1], log)

	text = get_payload(msg)
	if text: text = get_summary(text)

	sql.execute('UPDATE Message SET folder=?, filename=?, size=?, "from"=?, replyto=?, subject=?, "text"=?, "date"=?, received=? WHERE id=?', (
		folderid, filename, os.path.getsize(f), fromaddr, replytoaddr, subject, text, date, received, row))

	# handle recipients
	seen = set()
	for recptype in ('to', 'cc'):
		for realname, addr in email.utils.getaddresses(msg.get_all(recptype, [])):
			realname = decode_and_normalize(realname)
			addr = get_address(sql, addr)
			if realname: names.setdefault(addr, collections.Counter())[realname] += 1
			if not addr in seen:
				seen.add(addr)
				sql.execute('INSERT INTO "To" (message,address,cc) VALUES (?,?,?)', (row, addr, recptype == 'cc'))

	# handle threads
	inreplyto = msg['in-reply-to']
	if inreplyto is not None:
		inreplyto = re.findall('<[^>]*>', inreplyto)
		if inreplyto:
			sql.execute('UPDATE Message SET parent=? WHERE id=?', (get_message(sql, inreplyto[0]), row))
	refs = [get_message(sql, mid) for mid in re.findall('<[^>]*>', ' '.join(msg.get_all('references', [])))]
	refs = [r for r in refs if r != row]
	refs.append(row)
	prevref = refs[0]
	for ref in refs[1:]:
		sql.execute('UPDATE Message SET parent=? WHERE id=? AND parent IS NULL', (prevref, ref))
		prevref = ref
	# FIXME trust earliest ref rather than first encountered ref?

def import_dir(rootdir, sql, log):

	log('Scanning for files...')
	allfiles = list(os.walk(rootdir))

	log('Loading messages...')
	names = {}
	for dirpath, dirnames, filenames in allfiles:
		if filenames:
			log('Directory: %s', dirpath)
			subdir = dirpath[len(rootdir):]
			res = tuple(sql.execute('SELECT id FROM Folder WHERE name=?', (subdir,)))
			if res:
				(folderid,), = res
				existing = frozenset(f for f, in sql.execute('SELECT filename FROM Message WHERE folder=?', (folderid,)))
			else:
				folderid = sql.execute('INSERT INTO Folder (name) VALUES (?)', (subdir,)).lastrowid
				existing = frozenset()
			for filename in filenames:
				if filename not in existing:
					insert_message(sql, folderid, dirpath, filename, names, log)

	log('Setting names...')
	for addr, counter in names.items():
		most_common = counter.most_common(1)
		if most_common:
			(name, count), = most_common
			sql.execute('UPDATE Address SET name=? WHERE name IS NULL AND id=?', (name, addr))
	sql.execute("UPDATE Address SET name=NULL WHERE address=''")

def merge_orphans(sql, log):
	log('Merging messages...')
	# we merge orphaned messages (no message-id) with missing messages (message-id referenced by other messages but not found)

	candidates = {}
	used = set()
	for parent, addr, row, date, subject in sql.execute(
		'SELECT m.parent, t.address, m.id, c.date, c.subject FROM Message m, Message c, "To" t WHERE c.parent=m.id AND t.message=c.id AND m.filename IS NULL AND c.date IS NOT NULL'):
		candidates.setdefault((parent, addr), []).append((row, date, subject.lower()))
	def get_candidates(parent, addr, date, subject):
		res = candidates.get((parent, addr))
		matches = set()
		if res:
			# FIXME should compare subject case sensitively after 'RE:'
			if subject is not None: subject = subject.lower()
			for row, childdate, childsubject in res:
				if row not in used:
					if childdate > date:
						if subject is None or subject == childsubject:
							matches.add(row)
		return matches
	
	def mergeinto(missing, row, parent, rowdata):
		log('Merging message %r into %r', row, missing)
		used.add(missing)
		sql.execute('UPDATE Message SET folder=?,filename=?,size=?,"from"=?,replyto=?,subject=?,text=?,date=?,received=?,parent=? WHERE id=?', rowdata+(parent,missing))
		sql.execute('UPDATE "To" SET message=? WHERE message=?', (missing,row))
		sql.execute('DELETE FROM Message WHERE id=?', (row,))
	for row,folder,filename,size,from_,replyto,subject,text,parent,date,received in tuple(sql.execute(
		'SELECT id,folder,filename,size,"from",replyto,subject,text,parent,date,received FROM Message WHERE messageid IS NULL AND date IS NOT NULL')):
		rowdata = folder,filename,size,from_,replyto,subject,text,date,received
		if parent is not None:
			# has parent, so cannot be root...
			# if leaf, then no children so no missing entry to merge with, and parent already set...
			# so we only need to check for missing inner conversation entries:
			missing = get_candidates(parent, replyto, date, None)
			if not missing and subject and subject.lower() != 're:':
				resubject = subject if subject.lower().startswith('re:') else 're: '+subject
				missing = get_candidates(None, replyto, date, resubject)
			if len(missing) == 1:
				missing, = missing
				mergeinto(missing, row, parent, rowdata)
		elif subject:
			if subject.lower().startswith('re:'):
				# TODO this is broken/incomplete/slow ...
				rootsubject = subject[3:].lstrip()
				if rootsubject:
					# node of convo -> merge AND set parent!
					# FIXME do get_candidates first, then find parent based on candidates
					missing = tuple(sql.execute(
						# FIXME collate nocase on p.subject?
						'SELECT DISTINCT m.id, p.id FROM Message m, Message c, Message p, "To" childto, "To" orphanto WHERE c.parent=m.id AND childto.message=c.id AND orphanto.message=? AND m.filename IS NULL AND childto.address=? AND orphanto.address=p.replyto AND c.date>? AND p.date<? AND c.subject=? COLLATE NOCASE AND (p.subject=? OR p.subject=?) ORDER BY p.date DESC, c.date ASC',
						(row,replyto,date,date,subject,subject,rootsubject)))
					if missing:
						missing, parent = missing[0] # FIXME taking most recent parent and least recent child; false positives?
						mergeinto(missing, row, parent, rowdata)
					# TODO leaf of convo -> no merge (no children, no missing entry), but set parent!
			else:
				# root of convo
				# TODO check if message not too far before child
				missing = get_candidates(None, replyto, date, 're: '+subject)
				if len(missing) == 1:
					missing, = missing
					mergeinto(missing, row, parent, rowdata)

def main():
	def log(s, *args): print(s % args)
	sql = sqlite3.connect('data/cache.sqlite3', isolation_level=None)
	sql.executescript(open(os.path.join(os.path.dirname(__file__), 'init.sql')).read())
	import_dir('data/mail/', sql, log)
	merge_orphans(sql, log)
	log('Done.')

main()

