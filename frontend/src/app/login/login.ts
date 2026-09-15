import { Component, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { Api } from '../api';

@Component({
  selector: 'app-login',
  templateUrl: './login.html',
})
export class Login {
  private api = inject(Api);
  private router = inject(Router);

  protected error = signal<string | null>(null);
  protected enviando = signal(false);

  entrar(evento: Event, email: string, password: string): void {
    evento.preventDefault();
    this.error.set(null);
    this.enviando.set(true);
    this.api.login(email, password).subscribe({
      next: () => this.router.navigate(['/']),
      error: (e: HttpErrorResponse) => {
        this.enviando.set(false);
        this.error.set(e.status === 401 ? 'Email o contraseña incorrectos' : 'No se pudo conectar con la API');
      },
    });
  }
}
