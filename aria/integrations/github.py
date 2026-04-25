import time

from textual import work
from textual.widgets import Static

from aria.core.config import save_config

class AriaGithubMixin:
    @work(thread=True)
    def _github_login_flow(self) -> None:
        client_id = self.config.get("github_client_id")
        if not client_id:
            def mount_err(): self.query_one("#chat-log").mount(Static("[bold #f472b6]Error:[/bold #f472b6] Client ID GitHub tidak ditemukan di config.", classes="tool-box"))
            self.call_from_thread(mount_err); return

        def mount_msg(m): self.call_from_thread(lambda: self.query_one("#chat-log").mount(Static(m, classes="tool-box")))
        
        mount_msg("[bold #71d1d1]Memulai GitHub Device OAuth Flow...[/bold #71d1d1]")
        
        try:
            import requests
            res = requests.post("https://github.com/login/device/code", 
                                data={"client_id": client_id, "scope": "repo,read:user,workflow"}, 
                                headers={"Accept": "application/json"}, timeout=15)
            if res.status_code != 200:
                mount_msg(f"[bold #f472b6]Gagal mendapatkan kode dari GitHub:[/bold #f472b6]\n{res.text}")
                return

            data = res.json()
            user_code = data["user_code"]
            device_code = data["device_code"]
            uri = data["verification_uri"]
            interval = data.get("interval", 5)

            mount_msg(f"\n[bold #d1a662]ACTION REQUIRED![/bold #d1a662]\n1. Buka: [bold underline]{uri}[/bold underline]\n2. Masukkan kode: [bold #71d1d1]{user_code}[/bold #71d1d1]\n\n[italic #7b6b9a]Menunggu konfirmasi dari GitHub...[/italic #7b6b9a]")

            while not self._cancel_stream:
                time.sleep(interval)
                t_res = requests.post("https://github.com/login/oauth/access_token",
                                      data={"client_id": client_id, "device_code": device_code, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
                                      headers={"Accept": "application/json"}, timeout=15)
                t_data = t_res.json()

                if "access_token" in t_data:
                    token = t_data["access_token"]
                    self.config["github_oauth_token"] = token
                    if "refresh_token" in t_data:
                        self.config["github_refresh_token"] = t_data["refresh_token"]
                    save_config(self.config)
                    
                    try:
                        from github import Github
                        g = Github(token)
                        user = g.get_user()
                        mount_msg(f"[bold #71d1d1]✓ Berhasil Login sebagai:[/bold #71d1d1] [bold #d1a662]@{user.login}[/bold #d1a662] ({user.name})\n[#7b6b9a]Aria Assist Code kini sudah aktif![/#7b6b9a]")
                    except Exception as ge:
                        mount_msg(f"[bold #71d1d1]✓ Berhasil Login![/bold #71d1d1] [#7b6b9a](Gagal mengambil profil: {ge})[/#7b6b9a]")
                    return

                err = t_data.get("error")
                if err == "authorization_pending": continue
                if err == "slow_down": interval += 5; continue
                mount_msg(f"[bold #f472b6]Login Gagal/Dibatalkan:[/bold #f472b6] {err}")
                break
        except Exception as e:
            mount_msg(f"[bold #f472b6]Terjadi kesalahan saat login:[/bold #f472b6] {e}")

