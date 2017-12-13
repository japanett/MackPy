import atexit
import getpass
import os
import pickle
import signal
from tkinter import *

import pandas as pd
import requests
from bs4 import BeautifulSoup
from lxml import html

from entities import Materia, Topico, Subtopico, Tarefa
from util import *
from requesthandler import *

# ----------------------------------------------------
#                       SETUP
# ----------------------------------------------------
signal.signal(signal.SIGINT | signal.SIGKILL, exit_gracefully)  # does OR gating work in this scenario?

class Mackenzie():
	def __init__(self, recall=False, cross_plat_config_file='~/mack.ini', cookie_file='cookies'):
		self.config_file = os.path.expanduser(cross_plat_config_file)
		self.cookie_file = cookie_file
		try:
			self.config = pickle.load(open(self.config_file, 'rb'))
		except:
			self.config = {'materias_filepath': 'materias.mack'}
		if recall: self.recall()
		self.new_materias = None
		self._moodle_home = 'http://moodle.mackenzie.br/moodle/'
		self._moodle_login = self._moodle_home + 'login/index.php?authldap_skipntlmsso=1'
		self._tia_home = 'https://www3.mackenzie.br/tia/'
		self._tia_index = self._tia_home + 'index.php'
		self._tia_verifica = self._tia_home + 'verifica.php'
		self._tia_index2 = self._tia_home + 'index2.php'
		self._tia_horarios = self._tia_home + 'horarChamada.php'
		self._tia_notas = self._tia_home + 'notasChamada.php'
		self.session = requests.session()
		self.logged_in_tia = False
		self.logged_in_moodle = False
		self.logging_in_moodle = False
		self.logging_in_tia = False
		try:
			self.session.cookies = pickle.load(open(self.cookie_file, 'rb'))
		except:
			pass
		atexit.register(self.dump_cookie_file)
		atexit.register(self.dump_config_file)
		atexit.register(self.save)
		self._usage = '''Mack App\n\nUsage: python3 mackapp.py [-g] [-m tia] [-p senha] [-i] [-h] [-v] targets\n
				Options:
					-g      interface gráfica
					-h 		isto
					-m 		tia do aluno
					-p		senha pre-configurada opcional
					-i		modo interativo
					-t      targets
					-v      modo detalhado

				Exemplos: 
					python3 mackapp.py -m 31417485

				target pode ser notas, horarios, tarefas no momento
			'''
		self._server_usage = '''Mack App\n\nUsage: python3 mackapp.py -b [bot_id_info]\n
						Options:
							-h 		isto
							-i		modo interativo
					'''

	def dump_cookie_file(self):
		pickle.dump(self.session.cookies, open(self.cookie_file, 'wb'))

	def dump_config_file(self):
		pickle.dump(self.config, open(self.config_file, 'wb'))

	def save(self):
		pickle.dump(self.materias, open(self.config['materias_filepath'], 'wb'))

	def recall(self):
		try:
			self.materias = pickle.load(open(self.config['materias_filepath'], 'rb'))
			return True
		except:
			self.materias = None
			return False

	# ----------------------------------------------------
	#                       MOODLE
	# ----------------------------------------------------
	def login_moodle(self, v=False):
		self.logging_in_moodle = True
		res = self.session.get(self._moodle_home)
		data = {'username': self.config['user'], 'password': self.config['password']}
		cookies = dict(res.cookies)
		headers = dict(referer=self._tia_index)
		res = self.session.post(self._moodle_login, data=data, cookies=cookies, headers=headers, allow_redirects=True)
		self.logged_in_moodle = 'Minhas Disciplinas/Cursos' in res.text
		self.logging_in_moodle = False
		if v: print('Logged in.' if self.logged_in_moodle else 'Could not log in.')
		return self.logged_in_moodle

	def _diff(self, m, nm):
		return None  # the joint

	def get_materias(self, fetch=False, diff=False, v=0):
		if not self.logged_in_moodle and not self.logging_in_moodle: raise Exception('Not logged in Moodle')
		while self.logging_in_moodle: pass # wait to finish login
		if fetch: self.materias = self._fetch_materias(self.session.get(self._moodle_home).text, v=v)  # apply Diff
		if diff: return self.materias, self._diff(self.materias, self.new_materias)
		else: return self.materias

	def get_tarefas(self):
		tarefas = []
		for m in self.materias:
			tarefas.extend(m.all_tarefas())
		sorted(tarefas, lambda t: t.info['Data de entrega'])
		return tarefas

	def _fetch_materias(self, html, v=0):
		materias = []
		bs = BeautifulSoup(html, 'lxml')
		as_ = bs.find_all('a', href=True)
		for a in as_:
			if 'course' in a['href'] and a.get('title') is not None:
				title = a.get('title')
				if title not in materias and re.search(r'\s\d{4}/\d+$', title) is not None:
					materia = Materia(a['title'], a['href'])
					if not any(materia.name in m.name for m in materias):
						materias.append(materia)
		if v >= 1:
			print('Fetching..:')
			for m in materias: print(m.hash(), str(m))
		for materia in materias:
			bs = BeautifulSoup(self.session.get(materia.link).text, 'lxml')
			i = 1
			no_topic_name_count = 10
			while True:
				sec = bs.find(id='section-' + str(i))
				if sec is None: break
				as_ = BeautifulSoup(str(sec), 'lxml').find_all('a', href=True)
				topic_name = sec.get('aria-label')
				if not topic_name:
					no_topic_name_count -= 1
					if not no_topic_name_count: break
					continue
				materia.topicos.append(Topico(topic_name))
				for a in as_:
					if a.get('onclick') is not None:
						sub_topic_name, sub_topic_type = ' '.join(a.text.split()[:-1]), ''.join(a.text.split()[-1:])
						if sub_topic_name is None: continue
						sub_topic_link = a['href']
						t = materia.topicos[-1]
						if not any(sub_topic_name == st.name for st in t.subtopicos):
							t.subtopicos.append(Subtopico(sub_topic_name, sub_topic_link, sub_topic_type))
						if sub_topic_type == 'Tarefa':
							tarefa_page = BeautifulSoup(self.session.get(sub_topic_link).text, 'lxml')
							tarefa_name = tarefa_page.find_all('h2')[0].text
							tarefa_desc = tarefa_page.find_all('div', attrs={'id':'intro'})[0].text
							tarefa_table = tarefa_page.find_all('table', class_='generaltable')[0]
							tds = tarefa_table.find_all('td')
							j = 0
							tarefa = Tarefa(tarefa_name, tarefa_desc)
							tarefa_ik = None
							for td in tds:
								tarefa_attrib = td.text
								j += 1
								if j == 10: break  # exceeded useful table rows
								if not tarefa_ik:
									tarefa_ik = tarefa_attrib.rstrip()
								else:
									# if tarefa_ik == 'Data de entrega': tarefa_attrib = parse_datetime_moodle(tarefa_attrib)
									tarefa.info.update({tarefa_ik: tarefa_attrib})
									tarefa_ik = None
							if tarefa:
								tarefa.due_date = parse_datetime_moodle(tarefa.info['Data de entrega'])
								t.subtopicos[-1].tarefas.append(tarefa)
				i += 1
		return materias

	# ----------------------------------------------------
	#                       TIA
	# ----------------------------------------------------

	def login_tia(self, user, pwd, v=False):
		res = self.session.get(self._tia_index)
		token = list(set(html.fromstring(res.text).xpath("//input[@name='token']/@value")))[0]
		data = {'alumat': user, 'pass': pwd, 'token': token, 'unidade': '001'}
		cookies = dict(res.cookies)
		headers = dict(referer=self._tia_index)
		self.session.post(self._tia_verifica, data=data, cookies=cookies, headers=headers, allow_redirects=True)
		res = self.session.get(self._tia_index2).text
		self.logged_in_tia = user in res
		if v: print('Entrou no TIA')
		if 'manuten' in res: raise Exception('MANUTENCAO')
		return self.logged_in_tia

	def _extract_horarios(self, html): # TODO update self.materias instead
		if not self.logged_in_tia: raise Exception('Not logged in Moodle')
		refined = {}
		dias = {0: 'Seg', 1: 'Ter', 2: 'Qua', 3: 'Qui', 4: 'Sex', 5: 'Sab'}
		lists = pd.read_html(html)[1].values.tolist()
		for i in range(1, len(lists)):
			l = lists[i]
			hor = l[0]
			for j in range(1, len(l)):
				if dias[j - 1] not in refined:
					refined[dias[j - 1]] = []
					if hor not in refined[dias[j - 1]]: refined[dias[j - 1]] = {}
				try:
					refined[dias[j - 1]][hor] = l[j][:l[j].index('(') - 1]
				except:
					refined[dias[j - 1]][hor] = l[j]
		return refined

	def get_horarios(self):
		if not self.logged_in_tia: raise Exception('Not logged in Moodle')
		return self._extract_horarios(self.session.get(self._tia_horarios).text)

	def _extract_notas(self, html): # TODO same as above
		refined = {}
		cod_notas = {2: 'A', 3: 'B', 4: 'C', 5: 'D', 6: 'E', 7: 'F', 8: 'G', 9: 'H', 10: 'I', 11: 'J',
		             12: 'NI1', 13: 'NI2', 14: 'SUB', 15: 'PARTIC', 16: 'MI', 17: 'PF', 18: 'MF'}
		lists = pd.read_html(html)[1].values.tolist()
		for i in range(0, len(lists)):
			l = lists[i]
			cod_materia = l[0]
			nome_materia = l[1]
			refined[nome_materia] = {'id': cod_materia}
			for j in range(2, len(l)):
				if cod_notas[j] not in refined:
					refined[nome_materia][cod_notas[j]] = l[j]
		return refined

	def get_notas(self):
		if not self.logged_in_tia: raise Exception('Not logged in Moodle')
		return self._extract_notas(self.session.get(self._tia_notas).text)


# ----------------------------------------------------
#                       MAIN
# ----------------------------------------------------
def process_args(args):
	argskv = {}
	key = None
	value = None
	for a in args[1:]:
		if a.startswith('-'):
			key = a
		else:
			value = a
		if key is not None and value is not None:
			argskv[key[1:]] = value
			key = None
			value = None
		elif key is None:
			argskv[value] = True
		elif value is None:
			argskv[key[1:]] = True
	return argskv


def test_materias():
	mack = Mackenzie(recall=True)
	mack.login_moodle(v=True)
	materias = mack.get_materias(fetch=True)
	for m in materias:
		tarefas = m.all_tarefas()
		for t in tarefas:
			print(t)
		print('\n'*3)
	sys.exit(0)


def self_use(argv):
	argskv = process_args(argv)
	mack = Mackenzie()
	if 'h' in argskv:
		print(mack._usage)
		return
	v = 'v' in argskv
	i = 'i' in argskv or not argskv
	logged_in_tia = False
	logged_in_moodle = False
	command_seq = list(filter(lambda k: not k.startswith('-'), argskv.keys()))
	if not command_seq and not i: i = True  # if theres no command, force interactive
	m, n = None, None
	while not m or not p:  # TODO: have argskv override mack.config
		m = argskv['m'] if 'm' in argskv else mack.config['user'] if 'user' in mack.config else input('Matricula: ')
		p = argskv['p'] if 'p' in argskv else mack.config['password'] if 'password' in mack.config else getpass.getpass(
			'Senha: ')
	while True:
		if i:
			try:
				o = input(''' Operacoes:\n\tTarefas\n\tNotas\n\tHorarios\n\nOperacao: ''').lower()
			except Exception as e:
				print(e)
				continue
		else:
			try:
				o = command_seq.pop()
			except:
				break
		out = None
		if o == 'tarefas':
			if not logged_in_moodle: logged_in_moodle = mack.login_moodle(v=v)
			out = mack.get_materias()
		elif o == 'notas':
			if not logged_in_tia: logged_in_tia = mack.login_tia(m, p, v)
			out = mack.get_notas()
		elif o == 'horarios':
			if not logged_in_tia: logged_in_tia = mack.login_tia(m, p, v)
			out = mack.get_horarios()
		print(jsonify(out))
		if not i: break


def server_use(argv):
	argkv = process_args(argv)
	mack = Mackenzie(recall=True)
	mack.login_moodle(v=True)
	if 'h' in argkv:
		print(mack._server_usage)
		return
	bot = RequestHandler(mack)
	bot.start()
	bot.join()

def main(argv):
	test_materias()
	# server_use(argv)

if __name__ == '__main__':
	main(sys.argv)
