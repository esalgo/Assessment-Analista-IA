import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { Api } from './api';

/** Pone el token en cada request. Si la API responde 401 (token vencido o
 *  inválido), borra la sesión y vuelve al login. */
export const tokenInterceptor: HttpInterceptorFn = (req, next) => {
  const api = inject(Api);
  const router = inject(Router);
  const token = api.token();
  const conToken = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;

  return next(conToken).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401 && !req.url.endsWith('/auth/login')) {
        api.salir();
        router.navigate(['/login']);
      }
      return throwError(() => error);
    }),
  );
};
