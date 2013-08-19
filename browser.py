#!/usr/bin/python3

# show window asap, then continue loading:
from gi.repository import Gtk, GLib
win = Gtk.Window()
win.set_title('Mail')
win.set_default_size(1024, 800)
win.connect('destroy', Gtk.main_quit)
win.show()
while Gtk.events_pending(): Gtk.main_iteration()

import os, re, time, fnmatch, sqlite3
import emailview, util

PATH = 'data'

sql = sqlite3.connect(os.path.join(PATH, 'cache.sqlite3'), isolation_level=None)
sql.executescript(open(os.path.join(os.path.dirname(__file__), 'init.sql')).read())

MessageModel = util.NamedTreeStore(SELECTED=bool, FILENAME=str, CONTENT=str, SUBJECT=str, FROM=str, DATE=str, ID=int, LAST=str, FOLDER=str, SIZE=int, SIZESTR=str)

def build_model(condition, params, thread=True):
	print('Retrieving messages and building threads...')
	start = time.time()
	msgmodel = MessageModel()
	SELECT = ('SELECT m.id, m.parent, m.subject, m.text, m.date, m.received, m.size, m.filename, f.name, a.address, a.name'
		' FROM Message m LEFT JOIN Folder f ON m.folder=f.id LEFT JOIN Address a ON m."from"=a.id WHERE ')
	def add_row(parentrow, m):
		id, parent, subject, text, date, received, size, filename, folder, fromaddr, fromname = m
		dispsubject = subject or ('(No subject)' if filename else '(Missing message)')
		if not text: disptext = dispsubject
		elif not subject or re.match('(?i)re:', subject): disptext = text
		else: disptext = subject + ' / ' + text
		return msgmodel.append_named(parentrow,
				SELECTED=False,
				ID=id,
				FILENAME=filename,
				CONTENT=disptext,
				SUBJECT=dispsubject,
				FROM=fromname + ' <' + fromaddr + '>' if fromname else fromaddr,
				DATE=date or received,
				FOLDER=folder,
				LAST=None,
				SIZE=size or 0,
				SIZESTR=util.format_size(size) if size else None
		)
	messages = sql.execute(SELECT + condition, params)
	if thread:
		messages = dict((m[0], m) for m in messages)
		rows = {None: None}
		while messages: # FIXME handle loops?
			for m in list(messages.values()):
				parent = m[1]
				if parent in rows:
					del messages[m[0]]
					rows[m[0]] = add_row(rows[parent], m)
				elif not parent in messages:
					p, = sql.execute(SELECT + ' m.id=?', (parent,))
					messages[parent] = p
		def fill_last_reply(i):
			last_reply = '' if i is None else msgmodel.get_value(i, msgmodel.DATE) or ''
			i = msgmodel.iter_children(i)
			while not i is None:
				last_subreply = fill_last_reply(i)
				msgmodel.set_value(i, msgmodel.LAST, last_subreply)
				if last_subreply > last_reply: last_reply = last_subreply
				i = msgmodel.iter_next(i)
			return last_reply
		fill_last_reply(None)
		msgmodel.set_sort_column_id(msgmodel.LAST, Gtk.SortType.DESCENDING)
	else:
		for m in list(messages):
			add_row(None, m)
		msgmodel.set_sort_column_id(msgmodel.DATE, Gtk.SortType.DESCENDING)
	print('Took %ims' % ((time.time() - start) * 1000))
	return msgmodel

tree = Gtk.TreeView()

renderer = Gtk.CellRendererToggle()
renderer.props.activatable = True
def on_toggled(renderer, path): tree.get_model()[path][MessageModel.SELECTED] ^= True
renderer.connect('toggled', on_toggled)
col = Gtk.TreeViewColumn('', renderer, active=MessageModel.SELECTED)
tree.append_column(col)

tree.append_column(util.column('ID', util.textrenderer(), MessageModel.ID))
tree.append_column(util.column('Folder', util.textrenderer(0), MessageModel.FOLDER))
activitycol = util.column('Last activity', util.textrenderer(), MessageModel.LAST)
tree.append_column(activitycol)
tree.append_column(util.column('Date', util.textrenderer(), MessageModel.DATE))
tree.append_column(util.column('From', util.textrenderer(16), MessageModel.FROM))
tree.append_column(util.column('Size', util.textrenderer(align=1), MessageModel.SIZESTR, MessageModel.SIZE))
subjrenderer = util.textrenderer(80)
subjcol = util.column('Subject', subjrenderer, MessageModel.CONTENT)
tree.append_column(subjcol)
tree.set_expander_column(subjcol)

emailview = emailview.EmailView()

def on_select_mail(view):
	path, col = view.get_cursor()
	if not path: return
	row = tree.get_model()[path]
	filename = row[MessageModel.FILENAME]
	if filename is None:
		emailview.set_email(None)
	else:
		emailview.set_email(os.path.join(PATH, 'mail', row[MessageModel.FOLDER], filename))
tree.connect('cursor-changed', on_select_mail)

AddressModel = util.NamedTreeStore(ID=int, NAME=str, ADDRESS=str, COUNT=int, TOCOUNT=int, FROMCOUNT=int, SELECTED=bool)
addrmodel = AddressModel()
addresses = dict((row[1].lower(), row) for row in sql.execute('SELECT id, address, name FROM Address'))
fromcounts = dict(sql.execute('SELECT a, COUNT(*) FROM (SELECT "from" a FROM Message WHERE a IS NOT NULL UNION ALL SELECT "replyto" a FROM Message WHERE a<>"from" AND a IS NOT NULL) GROUP BY a'))
tocounts = dict(sql.execute('SELECT address, COUNT(*) FROM "To" GROUP BY address'))
def add_addresses(addr):
	addrs = fnmatch.filter(addresses, addr.lower())
	addrs = [addresses.pop(k) for k in addrs]
	if not addrs:
		print('No addresses match contact', addr)
	for id, address, name in addrs:
		tocount = tocounts.get(id, 0)
		fromcount = fromcounts.get(id, 0)
		addrmodel.append_named(groups[-1], ID=id, NAME=name, ADDRESS=address, COUNT=tocount+fromcount, TOCOUNT=tocount, FROMCOUNT=fromcount, SELECTED=True)
groups = [addrmodel.append_named(None, ID=-1, NAME=None, ADDRESS='Contacts', COUNT=0, TOCOUNT=0, FROMCOUNT=0, SELECTED=True)]
prevname = None
try: f = open(os.path.join(PATH, 'contacts.txt'))
except FileNotFoundError: pass
else:
	with f:
		for line in f:
			if line.strip():
				indent = 0
				while line[indent] == '\t': indent += 1
				name = line[indent:].rstrip()
				if indent >= len(groups):
					assert indent == len(groups)
					groups.append(addrmodel.append_named(groups[-1], ID=-1, NAME=None, ADDRESS=prevname, COUNT=0, TOCOUNT=0, FROMCOUNT=0, SELECTED=True))
				else:
					if prevname: add_addresses(prevname)
					while indent < len(groups)-1: groups.pop()
				prevname = name
if prevname: add_addresses(prevname)
if addresses:
	uncat = addrmodel.append_named(groups[0], ID=-1, NAME=None, ADDRESS='Uncategorized', COUNT=0, TOCOUNT=0, FROMCOUNT=0, SELECTED=True)
	for id, address, name in addresses.values(): # FIXME merge with add_addresses
		tocount = tocounts.get(id, 0)
		fromcount = fromcounts.get(id, 0)
		addrmodel.append_named(uncat, ID=id, NAME=name, ADDRESS=address, COUNT=tocount+fromcount, TOCOUNT=tocount, FROMCOUNT=fromcount, SELECTED=True)
def set_group_counts(root):
	i = addrmodel.iter_children(root)
	if i is None:
		return addrmodel.get_value(root, AddressModel.COUNT), addrmodel.get_value(root, AddressModel.FROMCOUNT), addrmodel.get_value(root, AddressModel.TOCOUNT)
	n = nf = nt = 0
	while not i is None:
		cn, cnf, cnt = set_group_counts(i)
		n += cn
		nf += cnf
		nt += cnt
		i = addrmodel.iter_next(i)
	addrmodel.set_value(root, AddressModel.COUNT, n)
	addrmodel.set_value(root, AddressModel.FROMCOUNT, nf)
	addrmodel.set_value(root, AddressModel.TOCOUNT, nt)
	return n, nf, nt
set_group_counts(groups[0])

addrlist = Gtk.TreeView(addrmodel)
renderer = Gtk.CellRendererToggle()
def on_toggled(renderer, path):
	m = addrlist.get_model()
	i = m.get_iter(path)
	v = not m.get_value(i, AddressModel.SELECTED)
	def toggle_iter(i):
		m.set_value(i, AddressModel.SELECTED, v)
		i = m.iter_children(i)
		while i:
			toggle_iter(i)
			i = m.iter_next(i)
	toggle_iter(i)
renderer.connect('toggled', on_toggled)
col = Gtk.TreeViewColumn('', renderer, active=AddressModel.SELECTED)
addrlist.append_column(col)

addrlist.append_column(util.column('Total', util.textrenderer(align=1), AddressModel.COUNT))
addrlist.append_column(util.column('To', util.textrenderer(align=1), AddressModel.TOCOUNT))
addrlist.append_column(util.column('From', util.textrenderer(align=1), AddressModel.FROMCOUNT))
col = util.column('Address', util.textrenderer(), AddressModel.ADDRESS)
addrlist.append_column(col)
addrlist.set_expander_column(col)
addrlist.append_column(util.column('Name', util.textrenderer(), AddressModel.NAME))
addrlist.expand_all()

filterentry = Gtk.Entry()
filterentry.set_placeholder_text('Search message subject and contents')

threadstoggle = Gtk.CheckButton('Threads')
threadstoggle.props.active = True

inverttoggle = Gtk.CheckButton('Invert results')

gobutton = Gtk.Button('Get messages')
def get_selected_addresses(i=None):
	m = addrlist.get_model()
	i = m.iter_children(i)
	while not i is None:
		for x in get_selected_addresses(i): yield x
		if m.get_value(i, AddressModel.SELECTED):
			x = m.get_value(i, AddressModel.ID)
			if x >= 0: yield x
		i = m.iter_next(i)

def on_go(b):
	sql.execute('CREATE TEMPORARY TABLE Selected (id INTEGER PRIMARY KEY)')
	try:
		sel = list(get_selected_addresses())
		#if sel: sql.execute('INSERT INTO Selected (id) VALUES ' + ','.join('(%i)'%i for i in sel)) # FIXME sqlite3.OperationalError: too many terms in compound SELECT
		if sel: sql.execute('INSERT INTO Selected (id) SELECT id FROM Address WHERE id IN (' + ','.join(str(i) for i in sel) + ')') # workaround
		query = 'SELECT m.id FROM Message m, Selected s WHERE m."from"=s.id OR m.replyto=s.id UNION SELECT t.message FROM "To" t, Selected s WHERE t.address=s.id'
		params = ()
		if filterentry.get_text() or datetoggle.get_active():
			query = 'SELECT id FROM Message WHERE id IN (' + query + ')'
			if filterentry.get_text():
				filtertext = '%'+filterentry.get_text()+'%' # FIXME escape
				query += ' AND (text LIKE ? OR subject LIKE ?)'
				params += (filtertext, filtertext)
			if datetoggle.get_active():
				query += ' AND COALESCE(date, received) BETWEEN ? AND ?'
				params += (get_date_text(fromcal), get_date_text(tocal) + '+')
		condition = ('m.filename IS NOT NULL AND m.id NOT IN (' if inverttoggle.props.active else 'm.id IN (') + query + ')'
		tree.set_model(build_model(condition, params, thread=threadstoggle.props.active))
		tree.expand_all()
		activitycol.set_visible(threadstoggle.props.active)
	finally:
		sql.execute('DROP TABLE Selected')
gobutton.connect('clicked', on_go)
filterentry.connect('activate', on_go)

subjtoggle = Gtk.CheckButton('Show content')
subjtoggle.props.active = True
def on_subjtoggle(t):
	i = MessageModel.CONTENT if t.props.active else MessageModel.SUBJECT
	subjcol.set_attributes(subjrenderer, text=i)
	subjcol.set_sort_column_id(i)
	tree.queue_draw() # XXX why doesn't this happen automatically?
subjtoggle.connect('toggled', on_subjtoggle)

def get_selected_messages(i=None):
	msgmodel = tree.get_model()
	i = msgmodel.iter_children(i)
	while not i is None:
		for x in get_selected_messages(i): yield x
		if msgmodel.get_value(i, MessageModel.SELECTED):
			yield tuple(msgmodel.get_value(i, col) for col in (MessageModel.ID, MessageModel.FOLDER, MessageModel.FILENAME))
		i = msgmodel.iter_next(i)
printbutton = Gtk.Button('Print selected')
def on_print(b):
	print('Selected:')
	for id, folder, filename in get_selected_messages():
		if folder and filename:
			print(os.path.join(folder, filename))
		else:
			print('no file for', id)
printbutton.connect('clicked', on_print)

datetoggle = Gtk.CheckButton('Filter by date range')
datebox = Gtk.HBox()
datebox.set_spacing(util.SPACING)
fromcal = Gtk.Calendar()
tocal = Gtk.Calendar()
def sync_dates(cal):
	y, m, d = cal.get_date()
	if d and fromcal.get_date() > tocal.get_date():
		target = tocal if cal is fromcal else fromcal
		target.select_month(m, y)
		target.select_day(d)
def get_date_text(cal):
	y, m, d = cal.get_date()
	return '%04i-%02i-%02i' % (y, m+1, d)
for cal in (fromcal, tocal):
	# We delay the call to sync_dates, because when clicking a day outside the
	# current month, GTK will only change the day AFTER triggering day-selected
	# for the month change...
	cal.connect('day-selected', lambda cal: GLib.idle_add(sync_dates, cal, priority=GLib.PRIORITY_HIGH))
	datebox.pack_start(cal, True, True, 0)
	cal.show()
datebox.set_no_show_all(True)
datetoggle.connect('toggled', lambda t: datebox.set_visible(t.get_active()))

# right pane
hbox = Gtk.HBox()
hbox.set_spacing(util.SPACING)
hbox.pack_start(subjtoggle, False, True, 0)
hbox.pack_start(printbutton, False, True, 0)

vbox = Gtk.VBox()
vbox.set_spacing(util.SPACING)
vbox.pack_start(hbox, False, True, 0)
vbox.pack_start(util.scrolled(tree), True, True, 0)

vpaned = Gtk.VPaned()
vpaned.pack1(vbox)
vpaned.pack2(emailview)
vpaned.set_position(450)

# left pane
hbox = Gtk.HBox()
hbox.set_spacing(util.SPACING)
hbox.pack_start(inverttoggle, False, True, 0)
hbox.pack_start(threadstoggle, False, True, 0)
hbox.pack_start(gobutton, True, True, 0)

vbox = Gtk.VBox()
vbox.set_spacing(util.SPACING)
vbox.pack_start(util.scrolled(addrlist), True, True, 0)
vbox.pack_start(datetoggle, False, True, 0)
vbox.pack_start(datebox, False, True, 0)
vbox.pack_start(filterentry, False, True, 0)
vbox.pack_start(hbox, False, True, 0)

# window
hpaned = Gtk.HPaned()
hpaned.pack1(vbox)
hpaned.child_set_property(vbox, 'shrink', False)
hpaned.pack2(vpaned)
hpaned.set_position(350)

win.add(hpaned)
win.show_all()
win.set_border_width(util.SPACING)

Gtk.main()

