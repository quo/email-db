from gi.repository import Gtk, Pango
import math, re

SPACING = 6

def format_size(bytes):
	unit = int(math.log(bytes+1, 1024) + .05)
	if not unit: return str(bytes) + ' B'
	return '%.2f %siB' % (bytes / 1024.0 ** unit, 'KMGT'[unit-1])

ENTITIES = dict(nbsp=' ',amp='&',gt='>',lt='<',quot='"',apos="'")
def _decode_entity(match):
	e = match.group(1)
	if e.startswith('#x') or e.startswith('#X'): return chr(int(e[2:], 16))
	if e.startswith('#'): return chr(int(e[1:]))
	return ENTITIES.get(e, '&'+e+';')
def decode_entities(text):
	return re.sub('&([^;]*);', _decode_entity, text)

def NamedTreeStore(**params):
	names = list(params)
	class NamedTreeStore(Gtk.TreeStore):
		def __init__(self):
			Gtk.TreeStore.__init__(self, *params.values())
		def append_named(self, parent, **params):
			return self.append(parent, tuple(params[n] for n in names))
	for col, name in enumerate(names):
		setattr(NamedTreeStore, name, col)
	return NamedTreeStore

def scrolled(widget):
	s = Gtk.ScrolledWindow()
	s.add(widget)
	s.set_shadow_type(Gtk.ShadowType.IN)
	return s

def textrenderer(width=None, align=None):
	renderer = Gtk.CellRendererText()
	if width is not None:
		renderer.props.ellipsize = Pango.EllipsizeMode.END
		renderer.props.width_chars = width
	if align is not None:
		renderer.props.xalign = align
	return renderer

def column(label, renderer, column, sortcolumn=None):
	col = Gtk.TreeViewColumn(label, renderer, text=column)
	col.set_resizable(True)
	col.set_sort_column_id(column if sortcolumn is None else sortcolumn)
	return col
