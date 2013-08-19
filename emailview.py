from gi.repository import Gtk, Pango
import os, math, email.feedparser, re, time, sys, fnmatch
import util

PartModel = util.NamedTreeStore(MESSAGE=object, LABEL=str)

class EmailView(Gtk.Notebook):
	def __init__(self):
		Gtk.Notebook.__init__(self)

		self.cur = None

		self.buf = Gtk.TextBuffer()
		text = Gtk.TextView.new_with_buffer(self.buf)
		text.set_border_width(util.SPACING)
		text.set_editable(False)
		text.set_cursor_visible(False)

		richview = Gtk.VBox()
		headers = Gtk.Label('TODO headers') # from, to, cc, subject, date
		richview.pack_start(headers, False, True, 0)

		self.parts = Gtk.TreeView()
		self.parts.set_headers_visible(False)
		self.parts.append_column(Gtk.TreeViewColumn('Part', Gtk.CellRendererText(), text=PartModel.LABEL))
		def on_select_part(view):
			path, col = view.get_cursor()
			if not path: return
			row = view.get_model()[path]
			self.show_part(row[PartModel.MESSAGE])
		self.parts.connect('cursor-changed', on_select_part)
		def on_activate_part(view, path, col):
			row = view.get_model()[path]
			msg = row[PartModel.MESSAGE]
			d = Gtk.FileChooserDialog('Save', self.get_toplevel(), Gtk.FileChooserAction.SAVE, (Gtk.STOCK_SAVE, Gtk.ResponseType.OK, Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))
			d.set_do_overwrite_confirmation(True)
			if msg.get_filename(): d.set_current_name(msg.get_filename())
			if d.run() == Gtk.ResponseType.OK:
				open(d.get_filename(), 'wb').write(msg.get_payload(decode=True))
			d.destroy()
		self.parts.connect('row-activated', on_activate_part)
		self.scrolledparts = util.scrolled(self.parts)

		self.richbuf = Gtk.TextBuffer()
		richtext = Gtk.TextView.new_with_buffer(self.richbuf)
		richtext.set_border_width(util.SPACING)
		richtext.set_editable(False)
		richtext.set_cursor_visible(False)
		richtext.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
		self.viewer_text = util.scrolled(richtext)
		self.viewer_text.show_all()

		# TODO
		#self.av = gtkimageview.AnimView()
		#self.av.connect('button-release-event', lambda w, e: w.grab_focus())
		#self.viewer_image = gtkimageview.ImageScrollWin(self.av)
		#self.viewer_image.show_all()

		self.richpaned = Gtk.HPaned()
		self.richpaned.set_position(100)
		self.richpaned.pack1(self.scrolledparts)
		richview.pack_start(self.richpaned, True, True, 0)
		
		scrolledtext = util.scrolled(text)
		scrolledtext.props.margin = util.SPACING
		self.append_page(scrolledtext, Gtk.Label('Raw'))
		richview.props.margin = util.SPACING
		self.append_page(richview, Gtk.Label('Message'))

	def show_part(self, msg):
		curviewer = self.richpaned.get_child2()
		if not curviewer is None: self.richpaned.remove(curviewer)
		if msg is None: return
		charset = msg.get_charset()
		type = msg.get_content_type()
		payload = msg.get_payload(decode=True)
		if type.startswith('text/'):
			payload = payload.decode(msg.get_content_charset() or (charset.input_codec if charset else 'iso-8859-1'), 'replace')
			if type == 'text/html':
				text = payload
				text = re.sub('\\s+', ' ', text)
				text = re.sub('(?i)<head[^>]*>.*?</head>', '', text)
				text = re.sub('(?i)<style[^>]*>.*?</style>', '', text)
				text = re.sub('(?i)<a ([^>]* )?href="([^"]*)"[^>]*>', lambda m: ' [ ' + m.group(2) + ' ] ', text)
				text = re.sub('(?i)<(br|div|blockquote|table|p|tr)[^>]*>', '\n', text)
				text = re.sub('<[^>]*>', '', text)
				text = util.decode_entities(text)
				text = re.sub('\n\\s*\n(\\s*\n)+', '\n\n', text)
				self.richbuf.props.text = text.strip()
			else:
				text = payload
				text = re.sub('\n\\s*\n(\\s*\n)+', '\n\n', text)
				self.richbuf.props.text = text.strip()
			self.richpaned.pack2(self.viewer_text)
		# TODO
		#elif type.startswith('image/'):
		#	loader = Gtk.gdk.PixbufLoader()
		#	loader.write(payload)
		#	loader.close()
		#	self.av.set_anim(loader.get_animation())
		#	self.richpaned.pack2(self.viewer_image)

	def set_email(self, filename):
		if filename == self.cur:
			return
		self.cur = filename
		if filename is None:
			self.buf.props.text = ''
			self.richbuf.props.text = ''
			self.scrolledparts.hide()
			return
		msgdata = open(filename, 'rb').read()
		# fill plain view
		self.buf.props.text = msgdata.decode('iso-8859-1', 'replace')
		self.buf.apply_tag(self.buf.create_tag(None, font='Monospace'), *self.buf.get_bounds())
		bold = self.buf.create_tag(None, weight=Pango.Weight.BOLD)
		start = self.buf.get_start_iter()
		nextline = 1
		if start.get_slice(self.buf.get_iter_at_offset(5)) == 'From ':
			start.forward_line()
			nextline = 2
		for end in map(self.buf.get_iter_at_line, range(nextline, self.buf.get_line_count())):
			text = start.get_slice(end)
			if text.lstrip() == text:
				match = start.forward_search(':', 0, end)
				if match:
					_, matchend = match
					self.buf.apply_tag(bold, start, matchend)
			if not text.strip(): break
			start = end
		self.buf.apply_tag(self.buf.create_tag(None, foreground='#888'), self.buf.get_start_iter(), start)
		# fill interpreted view
		parser = email.feedparser.BytesFeedParser()
		parser.feed(msgdata)
		msg = parser.close()
		if msg.is_multipart():
			partmodel = PartModel()
			def getparts(msg, parent):
				for child in msg.get_payload():
					if child.is_multipart():
						getparts(child, partmodel.append_named(parent, MESSAGE=None, LABEL=child.get_content_subtype()))
					else:
						label = '\n'.join(filter(bool, (child.get_content_type(), child.get_filename(), util.format_size(len(child.get_payload())))))
						partmodel.append_named(parent, MESSAGE=child, LABEL=label)
			getparts(msg, None)
			self.parts.set_model(partmodel)
			self.parts.expand_all()
			self.scrolledparts.show()
			self.parts.set_cursor((0,)) # FIXME find first html/text part
		else:
			self.scrolledparts.hide()
			self.parts.set_model(None)
			self.show_part(msg)
