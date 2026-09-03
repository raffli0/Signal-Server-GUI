
#include <iostream>
#include <cmath>
#include "/home/dedsec/PROJEK/RF-Propagation/Signal-Server/src/models/itwom3.0.hh"

__thread double *elev;

// Forward declare internal ITM functions from itwom3.0.cc
struct prop_type {
    double rch[2];
    double hg[2];
    double wn;
    double dh;
    double ens;
    double gme;
    double zgndreal;
    double zgndimag;
    double he[2];
    double dl[2];
    double the[2];
    int kwx;
    int mdp;
    double dist;
};
struct propv_type {
    double sgc;
    int lvar;
    int mdvar;
    int klim;
};
struct propa_type {
    double dlsa;
    double dx;
    double ael;
    double ak1;
    double ak2;
    double aed;
    double emd;
    double aes;
    double ems;
    double dls[2];
    double dla;
    double tha;
};

extern double qerfi(double q);
extern double avar(double zzt, double zzl, double zzc, prop_type &prop, propv_type &propv);
extern void qlrps(double fmhz, double zsys, double en0, int ipol, double eps, double sgm, prop_type &prop);
extern void qlrpfl(double elev[], int klimx, int mdvarx, prop_type &prop, propa_type &propa, propv_type &propv);

int main() {
    elev = (double *)calloc(150000, sizeof(double));
    double dkm = 70.0;
    int n = 700;
    elev[0] = n;
    elev[1] = (dkm * 1000.0) / n;
    for (int i = 2; i <= n + 2; i++) elev[i] = 400.0;

    double tht_m = 50.0, rht_m = 1500.0, eps = 15.0, sgm = 0.005, eno = 301.0, frq = 1200.0;
    int klim = 5, pol = 1;
    double conf = 0.50, rel = 0.70;

    for (int mdvar_choice : {12, 1, 2, 3}) {
        for (double loc_var : {0.0, 0.70, 0.80}) {
            prop_type prop;
            propv_type propv;
            propa_type propa;
            prop.hg[0] = tht_m;
            prop.hg[1] = rht_m;
            propv.klim = klim;
            prop.kwx = 0;
            propv.lvar = 5;
            prop.mdp = -1;
            propv.mdvar = mdvar_choice;
            double zc = qerfi(conf);
            double zr = qerfi(rel);
            double zl = qerfi(loc_var > 0 ? loc_var : 0.50);
            
            double zsys = 400.0;
            qlrps(frq, zsys, eno, pol, eps, sgm, prop);
            qlrpfl(elev, propv.klim, propv.mdvar, prop, propa, propv);
            double fs = 32.45 + 20.0 * log10(frq) + 20.0 * log10(prop.dist / 1000.0);
            double var_loss = avar(zr, zl, zc, prop, propv);
            double total_loss = fs + var_loss;
            double dBm = 48.29 + 6.0 - 0.5 - total_loss;
            printf("mdvar=%2d, loc=%.0f%% -> var_loss=%5.2f dB, total_loss=%6.2f dB, Rx dBm=%6.2f dBm\n",
                   mdvar_choice, loc_var * 100, var_loss, total_loss, dBm);
        }
    }
    return 0;
}
