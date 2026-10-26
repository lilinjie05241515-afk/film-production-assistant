"""All fixtures are synthetic TEST data; never opens personal skills/projects."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("filmprod_installer_tested", Path(__file__).with_name("installer.py"))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="filmprod-synthetic-install-")
        self.root = Path(self.tmp.name)
        self.app = self.root / "different-user/program"
        self.data = self.root / "different-drive/data"
        self.config = self.root / "different-user/config"
        self.package = self.make_package("1.6.0")

    def tearDown(self):
        self.tmp.cleanup()

    def make_package(self, version, schema=2):
        package = self.root / ("package-" + version)
        (package / "plugin/.codex-plugin").mkdir(parents=True)
        installer.write_json(package / "plugin/.codex-plugin/plugin.json", {"name": "film-production-agent", "version": version})
        installer.write_json(package / "plugin/.mcp.json", {"mcpServers": {}})
        # A small executable fixture checks installer behavior, not real filmprod acceptance.
        server = "import json,sys\nfor l in sys.stdin:\n r=json.loads(l)\n v={'tools':[{'name':str(i)} for i in range(12)]} if r['method']=='tools/list' else {'structuredContent':{'version':" + repr(version) + ", 'runtime_isolated':True,'ui_resource_present':True}}\n print(json.dumps({'id':r['id'],'jsonrpc':'2.0','result':v}),flush=True)\n"
        (package / "plugin/mcp_server.py").write_text(server, encoding="utf-8")
        (package / "TEST_ONLY.txt").write_text("synthetic, installer logic only", encoding="utf-8")
        self.rehash(package, version, schema)
        return package

    def rehash(self, package, version="1.6.0", schema=2):
        files = [{"path": p.relative_to(package).as_posix(), "sha256": installer.digest(p), "size": p.stat().st_size}
                 for p in sorted(package.rglob("*")) if p.is_file() and p.name != installer.MANIFEST]
        installer.write_json(package / installer.MANIFEST, {"schema_version": 1, "identity": installer.IDENTITY, "version": version,
                              "channel": "stable", "files": files,
                              "runtime": {"python": ">=3.11", "platforms": ["windows"], "data_schema_min": schema, "data_schema_max": schema}})

    def first_install(self):
        return installer.install(self.package, self.app, self.data, self.config)

    def stage_update(self):
        package = self.make_package("1.6.1")
        return installer.install(package, self.app, self.data, self.config)

    def path_alias(self, path):
        """A real, traversable alias without symlinks or Windows privileges."""
        anchor = path.parent / "TEST-existing-alias-segment"
        anchor.mkdir(parents=True, exist_ok=True)
        alias = anchor / ".." / path.name
        self.assertNotEqual(str(alias), str(path.resolve()))
        self.assertEqual(alias.resolve(), path.resolve())
        return alias

    def synthetic_tree(self):
        # Include directories as well as bytes so a rejected request cannot leave
        # a new release/deployment, empty staging tree, config, or catalog behind.
        return {p.relative_to(self.root).as_posix(): installer.digest(p) if p.is_file() else None
                for p in self.root.rglob("*")}

    def project(self, active=False, schema=2):
        root = self.root / "synthetic-TEST-project"
        (root / ".project").mkdir(parents=True)
        (root / "media").mkdir()
        (root / "media/test.txt").write_text("synthetic media bytes", encoding="utf-8")
        with installer.database(root / ".project/registry.sqlite3") as conn:
            conn.executescript("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE tasks(task_id TEXT PRIMARY KEY,data TEXT);")
            conn.executemany("INSERT INTO settings VALUES(?,?)", [("schema_version", json.dumps(schema)), ("project", json.dumps({"project_id": "TEST-synthetic", "test_only": True, "title": "TEST"}))])
            if active:
                conn.execute("INSERT INTO tasks VALUES(?,?)", ("TEST-task", json.dumps({"task_id": "TEST-task", "status": "in_progress"})))
        return root

    def test_first_install_is_independent_empty_and_fixed(self):
        result = self.first_install()
        self.assertEqual(result["status"], "installed")
        self.assertTrue(result["empty_catalog_created"])
        self.assertFalse(result["host_registration_performed"])
        config = installer.read_json(self.config / "user.json")
        self.assertIsNone(config["default_project"])
        self.assertEqual(config["cloud_bindings"], {})
        with installer.database(result["state"]["catalog_path"]) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM projects").fetchone()[0], 0)
        mcp = installer.read_json(Path(result["deployment"]) / "plugin/.mcp.json")["mcpServers"]["film-production"]
        self.assertIn(str(self.app / "deployments/1.6.0/plugin/mcp_server.py"), mcp["args"])
        self.assertNotIn("PLUGIN_ROOT", json.dumps(mcp))
        self.assertTrue(all(v["valid"] for v in installer.status(self.app)["versions"]))

    def test_all_files_verified_before_any_install(self):
        (self.package / "TEST_ONLY.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            self.first_install()
        self.assertFalse((self.app / "state.json").exists())
        self.assertFalse(self.config.exists())

    def test_extra_files_rejected(self):
        (self.package / "unlisted.txt").write_text("bad", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "未登记"):
            installer.verify_package(self.package)

    def test_archive_traversal_and_case_collision_rejected(self):
        for names in (("../escape",), ("A.txt", "a.txt"), ("a:b",), ("NUL.txt",)):
            path = self.root / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name in names: archive.writestr(name, "bad")
            with self.assertRaises(ValueError):
                installer.verify_package(path)
        self.assertFalse((self.root / "escape").exists())

    def test_valid_zip(self):
        path = self.root / "release.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for file in self.package.rglob("*"):
                if file.is_file(): archive.write(file, file.relative_to(self.package).as_posix())
        info = installer.verify_package(path)
        self.assertEqual(info["archive_sha256"], installer.digest(path))

    def test_check_and_stage_do_not_switch(self):
        self.first_install()
        package = self.make_package("1.6.1")
        result = installer.check_update(self.app, package)
        self.assertTrue(result["update_available"])
        self.assertFalse(result["switched"])
        installer.install(package, self.app, self.data, self.config)
        self.assertEqual(installer.status(self.app)["state"]["active_version"], "1.6.0")

    def test_same_location_aliases_accept_config_and_state_without_overwriting_user_config(self):
        self.first_install()
        catalog = self.data / "catalog/projects.sqlite3"
        aliases = {"app_root": self.path_alias(self.app), "data_root": self.path_alias(self.data),
                   "config_root": self.path_alias(self.config), "catalog_path": self.path_alias(catalog)}
        user_file = self.config / "user.json"
        user = installer.read_json(user_file)
        for key in ("app_root", "data_root", "catalog_path"):
            user[key] = str(aliases[key])
        user.update(default_project="TEST-existing-choice", cloud_bindings={"TEST-cloud": "preserve"},
                    custom_preference={"test_only": True, "text": "保留原配置和路径写法"})
        installer.write_json(user_file, user)
        original_user_bytes = user_file.read_bytes()
        state_file = self.app / "state.json"
        state = installer.read_json(state_file)
        for key in ("config_root", "data_root", "catalog_path"):
            state[key] = str(aliases[key])
        installer.write_json(state_file, state)
        with installer.database(catalog) as conn:
            conn.execute("INSERT INTO bindings VALUES('thread','TEST-alias-preserved','TEST-project')")
        original_catalog_bytes = catalog.read_bytes()

        package = self.make_package("1.6.1")
        result = installer.install(package, aliases["app_root"], aliases["data_root"],
                                   aliases["config_root"], catalog_path=aliases["catalog_path"])

        self.assertEqual(result["status"], "staged")
        self.assertFalse(result["empty_catalog_created"])
        self.assertEqual(user_file.read_bytes(), original_user_bytes)
        self.assertEqual(catalog.read_bytes(), original_catalog_bytes)
        saved = installer.read_json(state_file)
        self.assertEqual(saved, result["state"])
        self.assertEqual(saved["active_version"], "1.6.0")
        self.assertEqual(saved["staged_versions"], ["1.6.0", "1.6.1"])
        for key, path in (("config_root", self.config), ("data_root", self.data), ("catalog_path", catalog)):
            self.assertEqual(saved[key], str(path.resolve()))
            self.assertEqual(result["normalized_path_aliases"][key],
                             {"previous": str(aliases[key]), "resolved": str(path.resolve())})
        mcp = installer.read_json(Path(result["deployment"]) / "plugin/.mcp.json")["mcpServers"]["film-production"]
        self.assertEqual(mcp["env"]["FILMPROD_CATALOG_PATH"], str(catalog.resolve()))
        self.assertEqual(mcp["env"]["FILMPROD_CONFIG_PATH"], str(user_file.resolve()))
        self.assertTrue(all(v["valid"] for v in installer.status(self.app)["versions"]))

    def test_real_data_relocation_rejected_before_staging_with_existing_config(self):
        self.first_install()
        package = self.make_package("1.6.1")
        other_data = self.root / "TEST-unrelated-data"
        before = self.synthetic_tree()
        with self.assertRaisesRegex(ValueError, "现有配置 data_root 不匹配"):
            installer.install(package, self.app, other_data, self.config)
        self.assertEqual(self.synthetic_tree(), before)
        self.assertFalse(other_data.exists())

    def test_real_data_relocation_rejected_by_state_when_user_config_is_missing(self):
        self.first_install()
        package = self.make_package("1.6.1")
        (self.config / "user.json").unlink()
        other_data = self.root / "TEST-unrelated-data"
        before = self.synthetic_tree()
        # Hold catalog fixed: data-root itself must be checked against state.
        with self.assertRaisesRegex(ValueError, "升级必须沿用现有"):
            installer.install(package, self.app, other_data, self.config,
                              catalog_path=self.data / "catalog/projects.sqlite3")
        self.assertEqual(self.synthetic_tree(), before)
        self.assertFalse(other_data.exists())

    def test_real_config_relocation_rejected_before_staging(self):
        self.first_install()
        package = self.make_package("1.6.1")
        other_config = self.root / "TEST-unrelated-config"
        before = self.synthetic_tree()
        with self.assertRaisesRegex(ValueError, "升级必须沿用现有"):
            installer.install(package, self.app, self.data, other_config)
        self.assertEqual(self.synthetic_tree(), before)
        self.assertFalse(other_config.exists())

    def test_new_catalog_rejected_by_state_when_user_config_is_missing(self):
        self.first_install()
        catalog = self.data / "catalog/projects.sqlite3"
        with installer.database(catalog) as conn:
            conn.execute("INSERT INTO bindings VALUES('thread','TEST-original-catalog','TEST-project')")
        original_catalog_bytes = catalog.read_bytes()
        original_state_bytes = (self.app / "state.json").read_bytes()
        (self.config / "user.json").unlink()
        package = self.make_package("1.6.1")
        other_catalog = self.root / "TEST-unrelated-catalog/projects.sqlite3"
        before = self.synthetic_tree()
        with self.assertRaisesRegex(ValueError, "升级必须沿用现有"):
            installer.install(package, self.app, self.data, self.config, catalog_path=other_catalog)
        self.assertEqual(self.synthetic_tree(), before)
        self.assertEqual(catalog.read_bytes(), original_catalog_bytes)
        self.assertEqual((self.app / "state.json").read_bytes(), original_state_bytes)
        self.assertFalse((self.config / "user.json").exists())
        self.assertFalse(other_catalog.parent.exists())

    def test_same_version_idempotent_and_different_payload_rejected(self):
        self.first_install()
        self.assertEqual(self.first_install()["status"], "already_staged")
        (self.package / "TEST_ONLY.txt").write_text("changed same version", encoding="utf-8")
        self.rehash(self.package)
        with self.assertRaisesRegex(ValueError, "不可覆盖"):
            self.first_install()

    def test_existing_catalog_preserved_without_opening_registered_roots(self):
        catalog = self.root / "explicit-old-catalog.sqlite3"
        installer.catalog_init(catalog)
        with installer.database(catalog) as conn:
            conn.execute("INSERT INTO projects VALUES(?,?,?)", ("TEST-unknown", "X:/does-not-exist", json.dumps({"project_id": "TEST-unknown", "root": "X:/does-not-exist"})))
            conn.execute("INSERT INTO bindings VALUES(?,?,?)", ("thread", "TEST-chat", "TEST-unknown"))
        result = installer.install(self.package, self.app, self.data, self.config, catalog_path=catalog)
        self.assertFalse(result["empty_catalog_created"])
        with installer.database(catalog) as conn:
            self.assertEqual(conn.execute("SELECT binding_id FROM bindings").fetchone()[0], "TEST-chat")

    def test_active_task_and_incompatible_schema_refuse_switch(self):
        self.first_install(); self.stage_update()
        project = self.project(active=True)
        with self.assertRaisesRegex(ValueError, "quiescent"):
            installer.switch(self.app, "1.6.1")
        with self.assertRaisesRegex(ValueError, "在执行任务"):
            installer.switch(self.app, "1.6.1", [project], quiescent=True)
        with installer.database(project / ".project/registry.sqlite3") as conn:
            conn.execute("DELETE FROM tasks")
            conn.execute("UPDATE settings SET value='3' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError, "兼容区间"):
            installer.switch(self.app, "1.6.1", [project], quiescent=True)
        self.assertEqual(installer.status(self.app)["state"]["active_version"], "1.6.0")

    def test_successful_switch_and_full_rollback_preserve_newer_changes(self):
        self.first_install(); self.stage_update()
        project = self.project()
        result = installer.switch(self.app, "1.6.1", [project], quiescent=True)
        self.assertEqual(result["version"], "1.6.1")
        with self.assertRaisesRegex(ValueError, "禁止只切低版本"):
            installer.switch(self.app, "1.6.0", quiescent=True)
        config = installer.read_json(self.config / "user.json")
        config["after_update"] = "TEST"
        installer.write_json(self.config / "user.json", config)
        (project / "media/test.txt").write_text("newer media", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "quiescent"):
            installer.rollback(self.app)
        restored = installer.rollback(self.app, quiescent=True)
        self.assertEqual(restored["restored_version"], "1.6.0")
        self.assertNotIn("after_update", installer.read_json(self.config / "user.json"))
        self.assertEqual((project / "media/test.txt").read_text(encoding="utf-8"), "synthetic media bytes")
        newer = Path(restored["post_update_safety_backup"])
        self.assertEqual((newer / "projects/0/media/test.txt").read_text(encoding="utf-8"), "newer media")

    def test_injected_failure_restores_program_data_config_catalog(self):
        self.first_install(); self.stage_update()
        project = self.project()
        def failure(phase, state):
            if phase == "after_switch":
                with installer.database(project / ".project/registry.sqlite3") as conn:
                    conn.execute("UPDATE settings SET value='999' WHERE key='schema_version'")
                with installer.database(state["catalog_path"]) as conn:
                    conn.execute("INSERT INTO bindings VALUES('thread','TEST-new','TEST-project')")
                installer.write_json(self.config / "user.json", {"broken": True})
                raise RuntimeError("synthetic injected failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            installer.switch(self.app, "1.6.1", [project], fault=failure, quiescent=True)
        self.assertEqual(installer.status(self.app)["state"]["active_version"], "1.6.0")
        self.assertNotIn("broken", installer.read_json(self.config / "user.json"))
        with installer.database(project / ".project/registry.sqlite3") as conn:
            self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0], "2")
        with installer.database(installer.status(self.app)["state"]["catalog_path"]) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bindings").fetchone()[0], 0)

    def test_damaged_deployment_and_backup_rejected(self):
        self.first_install(); self.stage_update()
        result = installer.switch(self.app, "1.6.1", quiescent=True)
        (Path(result["backup"]) / "config/user.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "备份来源"):
            installer.rollback(self.app, quiescent=True)
        (self.app / "deployments/1.6.1/plugin/.mcp.json").write_text("tampered", encoding="utf-8")
        self.assertFalse(installer.status(self.app)["versions"][1]["valid"])

    def test_disable_uninstall_preserve_all_files(self):
        self.first_install()
        installer.deactivate(self.app, uninstall=True)
        self.assertFalse(installer.status(self.app)["state"]["enabled"])
        self.assertTrue((self.config / "user.json").exists())
        self.assertTrue((self.data / "catalog/projects.sqlite3").exists())
        self.assertTrue((self.app / "releases/1.6.0").is_dir())

    def test_duplicate_migration_is_reversible_and_six_skills_untouched(self):
        skills = self.root / "TEST-home/skills"
        control = skills / "film-production-agent"
        control.mkdir(parents=True)
        (control / "SKILL.md").write_text("TEST total control", encoding="utf-8")
        professional = skills / "director-agent"
        professional.mkdir()
        (professional / "SKILL.md").write_text("TEST independent method", encoding="utf-8")
        self.assertEqual(len(installer.duplicates([skills])["entries"]), 2)
        with self.assertRaisesRegex(ValueError, "skills"):
            installer.migrate_entry(control, skills / "backups")
        result = installer.migrate_entry(control, self.root / "TEST-backups")
        self.assertFalse(control.exists())
        self.assertTrue(professional.exists())
        receipt = Path(result["backup"]).with_suffix(".json")
        restored = installer.restore_entry(receipt)
        self.assertTrue(restored["restored"])
        self.assertEqual((control / "SKILL.md").read_text(encoding="utf-8"), "TEST total control")
        with self.assertRaises(ValueError): installer.migrate_entry(professional, self.root / "TEST-backups")

    def test_host_plan_is_separate_and_immutable_target(self):
        self.first_install()
        plan = installer.host_plan(self.app)
        self.assertFalse(plan["host_registration_performed"])
        market = installer.read_json(Path(plan["marketplace_root"]) / ".agents/plugins/marketplace.json")
        self.assertEqual(market["plugins"][0]["source"]["path"], "./plugin")
        self.assertTrue((Path(plan["marketplace_root"]) / "plugin/mcp_server.py").is_file())

    def test_cli_is_executable_and_missing_python_is_clear(self):
        script = Path(__file__).with_name("installer.py")
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(script), "verify", "--package", str(self.package)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["verified"])
        with self.assertRaisesRegex(ValueError, "Python 3.11"):
            installer.environment(self.root / "no-python.exe")

    @unittest.skipUnless(os.name == "nt", "Windows path limit")
    def test_overlong_destination_rejected_before_copy(self):
        long_app = self.root / ("x" * 160) / "app"
        with self.assertRaisesRegex(ValueError, "安装目录过长"):
            installer.install(self.package, long_app, self.data, self.config)
        self.assertFalse((long_app / "state.json").exists())

    def test_recover_prepared_crash_restores_previous_state(self):
        self.first_install(); self.stage_update()
        state = installer.status(self.app)["state"]
        backup, meta = installer.make_snapshot(self.app, state)
        installer.write_json(self.app / "transaction.json", {"phase": "prepared", "transaction": meta["transaction"], "backup": str(backup)})
        installer.write_json(self.app / "state.json", dict(state, active_version="1.6.1"))
        installer.write_json(self.config / "user.json", {"synthetic_crash_partial_write": True})
        result = installer.recover(self.app, quiescent=True)
        self.assertEqual(result["restored_version"], "1.6.0")
        self.assertNotIn("synthetic_crash_partial_write", installer.read_json(self.config / "user.json"))

    @unittest.skipUnless(os.name == "nt", "Windows bootstrap")
    def test_bootstrap_detects_python_and_forwards_arguments(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell unavailable")
        script = Path(__file__).with_name("bootstrap.ps1")
        result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Action", "verify", "--package", str(self.package)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"verified": true', result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
