#include <iostream>
#include <cmath>
#include "/home/dedsec/PROJEK/RF-Propagation/Signal-Server/src/models/itwom3.0.hh"

__thread double *elev;

int main() {
    elev = (double *)calloc(150000, sizeof(double));
    printf("Starting test_loss...\n"); fflush(stdout);
    double dkm = 70.0;
    int n = 700;
    elev[0] = n;
    elev[1] = (dkm * 1000.0) / n; // 100 meters per point
    for (int i = 2; i <= n + 2; i++) {
        elev[i] = 400.0; // flat 400m
    }
    double tht_m = 50.0;
    double rht_m = 1500.0;
    double eps = 15.0;
    double sgm = 0.005;
    double eno = 301.0;
    double frq = 1200.0;
    int klim = 5;
    int pol = 1;
    double conf = 0.50;
    char strmode[100];
    int errnum = 0;

    for (double rel : {0.50, 0.70, 0.80, 0.90}) {
        double loss = 0.0;
        point_to_point_ITM(tht_m, rht_m, eps, sgm, eno, frq, klim, pol, conf, rel, loss, strmode, errnum);
        double erp_w = 41.13;
        double rx_gain_dbi = 6.0;
        double rxp = erp_w / pow(10.0, (loss - 2.14) / 10.0);
        double dBm = 10.0 * log10(rxp * 1000.0) + rx_gain_dbi;
        std::cout << "Original SS point_to_point_ITM (rel " << rel*100 << "%): Loss=" << loss << " dB, dBm=" << dBm << std::endl;
    }
    return 0;
}
