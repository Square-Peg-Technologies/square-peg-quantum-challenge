# This file defines BaseCase and BaseCaseDescription
# classes that all case implementation should inherit
# with name Case and CaseDescription.
# grid-topology base classes are needed here (PTDF/Btilde construction from
# MATPOWER-style case data). The original package's DCOPF solver class and

import numpy as np


class BaseCase(object):
    def __init__(self, case_description, T):
        """
        This is the base class of Cases for DC optimal flow
        @param case_description:
            A class containing attributes: "branch", "bus", "gen".
            Preferably converted from MATPOWER cases.
        @param T:
            An int specifying home mamy time steps this case contains
            The DC optimal flow will be solved T times

        Attributes: All numpy arrays
            ** Grid topology is assumed to be fixed **
            Btilde:     Full bus susceptance matrix
            B:          Reduced bus susceptance matrix
            Atilde:     Full line-bus incidence matrix
            Dtilde:     Line-line susceptance matrix -- diagonal matrix satisfying Btilde = Atilde.T Dtilde Atilde
            PTDF:       Power Transfer Distribution Factors

            ** The following attributes can either be a column vector or a matrix with m column **
            ** If matrix at each step i%m-th column will be used **
            fbar:           Line powerflow limit
            pupbar, plobar:
                            Generator's generation limit
            power_demand:   Power demand
            generator_cost: Generating cost, the total cost assumed linear: c.T @ p_G
        """
        self.case_description = case_description
        self.T = T

        self.Btilde = None
        self.B = None
        self.Atilde = None
        self.Dtilde = None
        self.PTDF = None

        self.fbar = None
        self.phibar = None
        self.plobar = None
        self.power_demand = None
        self.generator_cost = None
        self.mu = None
        self.pg = None
        self.l = None

        if case_description is not None:
            self._init()

    def _init(self):
        """
        Load the attributes from case_description
        """
        print('loading {}'.format(self.case_description.name))
        mpc = self.case_description

        N = len(mpc.bus)
        L = len(mpc.branch)

        Atilde = np.zeros((L, N))
        for i in range(L):
            a = np.array(mpc.branch[i][:2])
            a -= 1  # due to MATLAB indexing
            Atilde[i, a[0]] = -1
            Atilde[i, a[1]] = 1

        d = np.array([mpc.branch[i][3] for i in range(L)])
        Dtilde = np.diag(1/d)

        if mpc.fbar is not None:
            fbar = np.array(mpc.fbar).reshape((-1,1))
        elif min([mpc.branch[i][5] for i in range(L)]) > 0:
            fbar = np.array([mpc.branch[i][5] for i in range(L)]).reshape((-1,1))
        else:
            raise NotImplementedError("Please create fbar attribute" + \
                 "or set rate A's in branch attribute to positive numbers in the casefile {}".
                                      format(self.case_description.name))


        generator_cost = np.zeros((N, 1))
        assert len(mpc.gen_cost) == len(mpc.gen)
        for i in range(len(mpc.gen)):
            # due to MATLAB indexing
            generator_cost[mpc.gen[i][0] - 1] = mpc.gen_cost[i]

        phibar = np.zeros((N, 1))
        for i in range(len(mpc.gen)):
            # due to MATLAB indexing
            phibar[mpc.gen[i][0] - 1] = mpc.gen[i][8]

        plobar = np.zeros((N, 1))
        for i in range(len(mpc.gen)):
            # due to MATLAB indexing
            plobar[mpc.gen[i][0] - 1] = mpc.gen[i][9]

        power_demand = np.array([[mpc.bus[i][2] for i in range(N)]]).T

        self.Btilde = Atilde.T @ Dtilde @ Atilde
        self.B = self.Btilde[1:, 1:]
        self.Atilde = Atilde
        self.Dtilde = Dtilde
        self.PTDF = np.insert(Dtilde @ Atilde[:, 1:] @ np.linalg.inv(self.B), 0, 0, axis=1)

        self.fbar = fbar
        self.phibar = phibar
        self.plobar = plobar
        self.power_demand = power_demand
        self.generator_cost = generator_cost


class BaseCaseDescription(object):
    def __init__(self, name):
        """
        This is the base class for CaseDescription class
        It must contain a name!

        In DCOPF package, CaseDescription must contain attributes:
        bus, gen, and branch
        They must be of the same form as the MATPOWER case files.
        In addition, the gen_cost should be populated with the linear
        cost of each generator given in gen.
        """

        self.name = name

        # factor for generator cost, assumed linear
        self.gen_cost = None

        # transmission line limit
        self.fbar = None

        # following from MATPOWER
        self.bus = None
        self.gen = None
        self.branch = None
