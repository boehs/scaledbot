import mwparserfromhell


def allow_bots(text, user):
	user = user.lower().strip()
	for tl in text.filter_templates():
		if tl.name.matches(['bots', 'nobots']):
			break
	else:
		return True
	for param in tl.params:
		bots = [x.lower().strip() for x in param.value.split(",")]
		if param.name == 'allow':
			if ''.join(bots) == 'none': return False
			for bot in bots:
				if bot in (user, 'all'):
					return True
		elif param.name == 'deny':
			if ''.join(bots) == 'none': return True
			for bot in bots:
				if bot in (user, 'all'):
					return False
	if (tl.name.matches('nobots') and len(tl.params) == 0):
		return False
	return True
