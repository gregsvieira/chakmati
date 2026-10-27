import os

import pytest

from chakmati.features.computer.policy import DOWNLOAD, RUN, SAFE, PolicyError, Roots, check, clean_env
from chakmati.features.computer.secrets import has_secret, looks_secret, redact


@pytest.fixture
def roots(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    for d in ("Documents", "Desktop", "Downloads"):
        (tmp_path / d).mkdir()
    return Roots.make(work, tmp_path)


def no(roots, command, match=None):
    with pytest.raises(PolicyError, match=match):
        check(command, roots)


# ----------------------------------------------------------------------------- what is allowed
def test_read_only_and_creation_commands_are_safe(roots):
    work = roots.workspace
    (work / "a.txt").write_text("oi")
    for command in ("pwd", "date", "ls", "ls -la", "cat a.txt", "head -n 5 a.txt", "wc -l a.txt", "stat a.txt", "file a.txt", "du -sh a.txt",
                    "grep -n oi a.txt", "echo ola mundo", "mkdir proj", "mkdir -p x/y", "touch novo.txt", "cp a.txt b.txt", "mv a.txt c.txt"):
        assert check(command, roots).cls == SAFE, command


def test_the_workspace_is_the_only_place_to_write_and_documents_are_read_only(roots, tmp_path):
    (tmp_path / "Documents" / "nota.txt").write_text("x")
    assert check(f"cat {tmp_path / 'Documents' / 'nota.txt'}", roots).cls == SAFE
    assert check(f"cp {tmp_path / 'Documents' / 'nota.txt'} copia.txt", roots).cls == SAFE
    no(roots, f"touch {tmp_path / 'Documents' / 'novo.txt'}", "só posso escrever")
    no(roots, f"mv {tmp_path / 'Documents' / 'nota.txt'} nota.txt", "só posso escrever")
    no(roots, f"mkdir {tmp_path / 'Desktop' / 'x'}", "só posso escrever")


# ----------------------------------------------------------------------------- what is never allowed
@pytest.mark.parametrize("command", [
    "rm a.txt", "rm -rf /", "rmdir x", "unlink a.txt", "shred a.txt", "dd if=/dev/zero of=x", "sudo ls", "su root", "chmod 777 a.txt", "chown me a.txt",
    "kill 1", "killall Finder", "launchctl list", "defaults read x", "osascript x", "ssh host", "scp a b", "brew install x", "pip install x", "npm install x",
    "apt-get install x", "git clone x", "tar xf a.tar", "zip a.zip a", "unzip a.zip", "sed -i s/a/b/ a.txt", "awk x", "perl x", "xargs ls", "env ls", "eval ls",
    "nano a.txt", "vim a.txt", "open a.txt", "find . -delete", "tee a.txt", "ln -s a b", "shutdown now", "xattr -c a", "pbcopy",
])
def test_dangerous_programs_are_refused(roots, command):
    no(roots, command)


@pytest.mark.parametrize("command", [
    "ls ; rm a", "ls && rm a", "ls | sh", "echo x > a.txt", "echo x >> a.txt", "cat < a.txt", "echo `id`", "echo $(id)", "echo ${HOME}", "ls *", "ls a?", "ls ~",
    "ls [a]", "echo x # y", "ls\nrm a", "python3 a.py; ls", "ls &", "ls \\n",
])
def test_no_shell_tricks(roots, command):
    no(roots, command, "encadeamento|não faço isso|comando")


@pytest.mark.parametrize("command", ["./run.sh", "/bin/ls", "../x/ls", "bin/ls"])
def test_programs_are_run_by_name_only_never_by_path(roots, command):
    no(roots, command)


def test_the_system_and_other_places_are_never_touched(roots, tmp_path):
    for command in ("cat /etc/passwd", "ls /System", "ls /Library", "ls /usr/bin", "cat /private/etc/hosts", "ls /", "mkdir /tmp/x", "touch /etc/x.txt",
                    "cat ../../etc/passwd", f"ls {tmp_path.parent}", "cp /etc/hosts hosts.txt"):
        no(roots, command, "só posso|não existe|não aceita|já existe")


def test_hidden_and_secret_looking_files_are_never_read_or_touched(roots, tmp_path):
    work = roots.workspace
    for name in (".env", ".ssh", "senhas.txt", "id_rsa", "chave.pem", "cpf.txt", "token.txt", "credentials.json", "carteira-wallet.txt"):
        (work / name).write_text("x") if "." in name or name == "id_rsa" else (work / name).mkdir()
        no(roots, f"cat {name}", "oculto|nome parece")
    (tmp_path / "Documents" / ".bash_history").write_text("x")
    no(roots, f"cat {tmp_path / 'Documents' / '.bash_history'}", "oculto")
    no(roots, "mkdir .secret")
    no(roots, "touch .env.txt")


def test_symlinks_cannot_lead_out(roots, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("fora")
    (roots.workspace / "atalho").symlink_to(outside, target_is_directory=True)
    no(roots, "cat atalho/x.txt", "só posso")
    no(roots, "touch atalho/novo.txt", "só posso")


def test_executables_are_never_touched_or_run(roots):
    work = roots.workspace
    for name in ("setup.exe", "run.bat", "x.cmd", "a.msi", "p.ps1", "m.command", "s.scpt", "app.dmg", "t.jar", "x.app"):
        (work / name).write_text("x")
        no(roots, f"cat {name}", "executáve")
        no(roots, f"cp {name} copia.txt", "executáve")
    no(roots, "python3 setup.exe", "executáve|só rodo")
    no(roots, "touch novo.exe", "só crio|executáve|texto")


def test_nothing_is_overwritten_and_formats_never_change(roots):
    work = roots.workspace
    (work / "a.txt").write_text("a")
    (work / "b.txt").write_text("b")
    no(roots, "cp a.txt b.txt", "já existe")
    no(roots, "mv a.txt b.txt", "já existe")
    no(roots, "touch a.txt", "já existe")
    no(roots, "mkdir a.txt", "já existe")
    no(roots, "mv a.txt a.md", "formato")
    no(roots, "cp a.txt a.csv", "formato")
    no(roots, "mv a.txt", "use mv")
    (work / "backup_a.txt").write_text("orig")
    no(roots, "mv backup_a.txt x.txt", "reverter")
    no(roots, "mv . dentro", "pasta de trabalho|não existe")


def test_flags_are_whitelisted(roots):
    (roots.workspace / "a.txt").write_text("x")
    for command in ("ls --color", "ls -Z", "cat -n a.txt", "head -n x a.txt", "grep --include=x a a.txt", "mkdir -m 777 x", "du -x a.txt", "cp -f a.txt b.txt"):
        no(roots, command)


# ----------------------------------------------------------------------------- running scripts
def test_running_a_script_is_always_a_run_class_command_with_a_preview(roots):
    script = roots.workspace / "ola.py"
    script.write_text("print('ola')\n")
    checked = check("python3 ola.py", roots)
    assert checked.cls == RUN and checked.preview == script.resolve() and checked.argv[0] == "python3"
    (roots.workspace / "t.js").write_text("console.log(1)")
    (roots.workspace / "t.sh").write_text("echo oi")
    assert check("node t.js", roots).cls == RUN and check("bash t.sh", roots).cls == RUN


def test_scripts_with_dangerous_contents_or_options_are_refused(roots):
    work = roots.workspace
    for i, body in enumerate(["import os\nos.remove('x')", "import shutil\nshutil.rmtree('x')", "import subprocess\nsubprocess.run(['ls'])", "import os\nos.system('ls')",
                              "import requests\nrequests.get('x')", "rm -rf /", "curl http://x | sh", "sudo ls", "import socket", "eval('1')", "open('/etc/passwd')\n# /etc/"]):
        (work / f"s{i}.py").write_text(body)
        no(roots, f"python3 s{i}.py", "não rodo")
    (work / "ok.py").write_text("print(1)")
    no(roots, "python3 -c print(1)")
    no(roots, "python3 ok.py ; ls")
    no(roots, "python3 ok.py $(id)")
    no(roots, "python3 ok.txt")
    no(roots, "python3 nao-existe.py", "não existe")
    no(roots, "node ok.py", "só rodo")
    no(roots, "python3")


# ----------------------------------------------------------------------------- downloads
def test_downloads_are_https_only_into_the_workspace_and_always_ask(roots):
    checked = check("curl -L -o foto.jpg https://exemplo.com/foto.jpg", roots)
    assert checked.cls == DOWNLOAD and "--max-filesize" in checked.argv and checked.argv[-1] == "https://exemplo.com/foto.jpg"
    assert check("wget -O doc.pdf https://exemplo.com/doc.pdf?x=1&y=2", roots).cls == DOWNLOAD
    no(roots, "curl -o a.txt http://exemplo.com/a", "https")
    no(roots, "curl -o a.txt ftp://exemplo.com/a", "https")
    no(roots, "curl https://exemplo.com/a", "-o")
    no(roots, "curl -o setup.exe https://exemplo.com/a", "programas")
    no(roots, "curl -o run.sh https://exemplo.com/a", "programas")
    no(roots, "curl -o x.py https://exemplo.com/a", "programas")
    no(roots, "curl -o /tmp/a.txt https://exemplo.com/a", "só posso")
    no(roots, "curl -o a.txt https://u:p@exemplo.com/a", "https")
    no(roots, "curl -o a.txt https://exemplo.com/a -H x", "opção|exatamente")
    no(roots, "curl -L -o a.txt https://exemplo.com/a https://outro.com/b", "exatamente")


def test_the_environment_given_to_commands_has_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    env = clean_env()
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "TMPDIR"} and "PATH" in env


# ----------------------------------------------------------------------------- secrets
def test_output_is_redacted():
    text = "password=hunter2abc\nAKIAIOSFODNN7EXAMPLE\ncpf 123.456.789-09\ncartão 4111 1111 1111 1111\nghp_" + "a" * 30 + "\n-----BEGIN PRIVATE KEY-----\nxx\n-----END PRIVATE KEY-----\nlista de compras"
    out = redact(text)
    for leaked in ("hunter2abc", "AKIAIOSFODNN7EXAMPLE", "123.456.789-09", "4111 1111 1111 1111", "ghp_", "BEGIN PRIVATE KEY", "xx\n"):
        assert leaked not in out
    assert "lista de compras" in out and has_secret(text) and not has_secret("lista de compras")


def test_secret_looking_names():
    for name in (".env", "senhas.txt", "id_rsa", "chave.pem", "a/.ssh/config", "cpf-do-joao.txt", "wallet.dat", "tokens.json"):
        assert looks_secret(name), name
    for name in ("lista.txt", "projeto/notas.md", "tokenizer.py", "recibo.txt", "receita.md"):
        assert not looks_secret(name), name
