import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { Api } from './api';
import { Login } from './login/login';
import { Tablero } from './tablero/tablero';

/** Sin sesión vigente, al login. Es comodidad de navegación: la protección
 *  real es que la API rechaza cualquier request sin token válido. */
const conSesion = () => inject(Api).sesion() !== null || inject(Router).createUrlTree(['/login']);

export const routes: Routes = [
  { path: 'login', component: Login },
  { path: '', component: Tablero, canActivate: [conSesion] },
  { path: '**', redirectTo: '' },
];
