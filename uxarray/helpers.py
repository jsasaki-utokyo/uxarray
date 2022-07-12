import numpy as np
import xarray as xr
from pathlib import PurePath

from .get_quadratureDG import get_gauss_quadratureDG, get_tri_quadratureDG
from numba import njit


# helper function to find file type
def determine_file_type(filepath):
    """Checks file path and contents to determine file type. Supports detection
    of UGrid, SCRIP, Exodus and shape file.

    Parameters: string, required
       Filepath of the file for which the filetype is to be determined.

    Returns: string
       File type: ug, exo, scrip or shp

    Raises:
       RuntimeError: Invalid file type
    """
    msg = ""
    mesh_filetype = "unknown"
    # exodus with coord
    try:
        # extract the file name and extension
        path = PurePath(filepath)
        file_extension = path.suffix

        # try to open file with xarray and test for exodus
        ext_ds = xr.open_dataset(filepath, mask_and_scale=False)["coord"]
        mesh_filetype = "exo"
    except KeyError as e:
        # exodus with coordx
        try:
            ext_ds = xr.open_dataset(filepath, mask_and_scale=False)["coordx"]
            mesh_filetype = "exo"
        except KeyError as e:
            # scrip with grid_center_lon
            try:
                ext_ds = xr.open_dataset(
                    filepath, mask_and_scale=False)["grid_center_lon"]
                mesh_filetype = "scrip"
            except KeyError as e:

                # check mesh topology and dimension
                try:
                    standard_name = lambda v: v is not None
                    # getkeys_filter_by_attribute(filepath, attr_name, attr_val)
                    # return type KeysView
                    ext_ds = xr.open_dataset(filepath, mask_and_scale=False)
                    node_coords_dv = ext_ds.filter_by_attrs(
                        node_coordinates=standard_name).keys()
                    face_conn_dv = ext_ds.filter_by_attrs(
                        face_node_connectivity=standard_name).keys()
                    topo_dim_dv = ext_ds.filter_by_attrs(
                        topology_dimension=standard_name).keys()
                    mesh_topo_dv = ext_ds.filter_by_attrs(
                        cf_role="mesh_topology").keys()
                    if list(mesh_topo_dv)[0] != "" and list(topo_dim_dv)[
                            0] != "" and list(face_conn_dv)[0] != "" and list(
                                node_coords_dv)[0] != "":
                        mesh_filetype = "ugrid"
                    else:
                        raise ValueError(
                            "cf_role is other than mesh_topology, the input NetCDF file is not UGRID format"
                        )
                except KeyError as e:
                    msg = str(e) + ': {}'.format(filepath)
    except (TypeError, AttributeError) as e:
        msg = str(e) + ': {}'.format(filepath)
    except (RuntimeError, OSError) as e:
        # check if this is a shp file
        # we won't use xarray to load that file
        if file_extension == ".shp":
            mesh_filetype = "shp"
        else:
            msg = str(e) + ': {}'.format(filepath)
    except ValueError as e:
        # check if this is a shp file
        # we won't use xarray to load that file
        if file_extension == ".shp":
            mesh_filetype = "shp"
        else:
            msg = str(e) + ': {}'.format(filepath)
    finally:
        if msg != "":
            msg = "Unable to determine file type, mesh file not supported" + ': {}'.format(
                filepath)
            raise ValueError(msg)

    return mesh_filetype


@njit
def _spherical_to_cartesian_unit_(node, r=6371):
    """Converts spherical (lat/lon) coordinates to cartesian (x,y,z).

    Final output is cartesian coordinates on a sphere of unit radius

    Parameters:
    -----------

    node: a list consisting of lat and lon

    Returns: numpy array
        Cartesian coordinates of length 3
    """
    lon = node[0]
    lat = node[1]
    lat, lon = np.deg2rad(lat), np.deg2rad(lon)
    x = r * np.cos(lat) * np.cos(lon)  # x coordinate
    y = r * np.cos(lat) * np.sin(lon)  # y coordinate
    z = r * np.sin(lat)  # z coordinate

    coord = np.array([x, y, z])
    # make it coord on a sphere with unit radius
    unit_coord = coord / np.linalg.norm(coord)

    return unit_coord


# Calculate the area of all faces.
@njit
def calculate_face_area(x,
                        y,
                        z,
                        quadrature_rule="gaussian",
                        order=4,
                        coords_type="spherical"):
    """Calculate area of a face on sphere.

    Parameters
    ----------

    x : list, required
        x-coordinate of all the nodes forming the face

    y : list, required
        y-coordinate of all the nodes forming the face

    z : list, required
        z-coordinate of all the nodes forming the face

    quadrature rule : string, optional
        triangular and Gaussian quadrature supported, expected values: "triangular" or "guaussian"

    order: int, optional
        Supported values of order for Gaussian Quadrature: 1 to 10
        Supported values of order for Triangular: 1, 4, 8, 10 and 12

    coords_type : str, optional
        coordinate type, default is spherical, can be cartesian also.
    """
    area = 0.0  # set area to 0
    order = order

    if quadrature_rule == "gaussian":
        dG, dW = get_gauss_quadratureDG(order)
    elif quadrature_rule == "triangular":
        dG, dW = get_tri_quadratureDG(order)
    else:
        raise ValueError(
            "Invalid quadrature rule, specify gaussian or triangular")

    num_nodes = len(x)

    # num triangles is two less than the total number of nodes
    num_triangles = num_nodes - 2
    # Using tempestremap GridElements: https://github.com/ClimateGlobalChange/tempestremap/blob/master/src/GridElements.cpp
    # loop thru all triangles
    for j in range(0, num_triangles):
        node1 = np.array([x[0], y[0], z[0]], dtype=np.float64)
        node2 = np.array([x[j + 1], y[j + 1], z[j + 1]], dtype=np.float64)
        node3 = np.array([x[j + 2], y[j + 2], z[j + 2]], dtype=np.float64)
        if (coords_type == "spherical"):
            node1 = _spherical_to_cartesian_unit_(node1)
            node2 = _spherical_to_cartesian_unit_(node2)
            node3 = _spherical_to_cartesian_unit_(node3)
        for p in range(len(dW)):
            if quadrature_rule == "gaussian":
                for q in range(len(dW)):
                    dA = dG[0][p]
                    dB = dG[0][q]
                    jacobian = calculate_spherical_triangle_jacobian(
                        node1, node2, node3, dA, dB)
                    area += dW[p] * dW[q] * jacobian
            elif quadrature_rule == "triangular":
                dA = dG[p][0]
                dB = dG[p][1]
                jacobian = calculate_spherical_triangle_jacobian_barycentric(
                    node1, node2, node3, dA, dB)
                area += dW[p] * jacobian

    return area


@njit
def get_all_face_area_from_coords(x,
                                  y,
                                  z,
                                  face_nodes,
                                  dim,
                                  quadrature_rule="triangular",
                                  order=4,
                                  coords_type="spherical"):
    """Given coords, connectivity and other area calculation params, this
    routine loop over all faces and return an numpy array with areas of each
    face.

    Parameters
    ----------

    x : ndarray, required
        x-coordinate of all the nodes

    y : ndarray, required
        y-coordinate of all the nodes

    z : ndarray, required
        z-coordinate of all the nodes

    face_nodes : 2D ndarray, required
         node ids of each face

    dim : int, required
         dimension

    quadrature_rule : str, optional
        "triangular" or "gaussian". Defaults to triangular

    order : int, optional
        count or order for Gaussian or spherical resp. Defaults to 4 for spherical.

    coords_type : str, optional
        coordinate type, default is spherical, can be cartesian also.

    Returns
    -------

    ndarray: area of all faces as a numpy array

        Examples
        --------

        >>> areas = ux.get_all_face_area
    """
    num_faces = face_nodes.shape[0]
    area = np.zeros(num_faces)  # set area of each face to 0

    for i in range(num_faces):

        num_face_nodes = len(face_nodes[i])
        face_x = np.zeros(num_face_nodes)
        face_y = np.zeros(num_face_nodes)
        face_z = np.zeros(num_face_nodes)

        for j in range(num_face_nodes):
            node_id = face_nodes[i][j]

            face_x[j] = x[node_id]
            face_y[j] = y[node_id]

            # check if z dimension
            if dim > 2:
                face_z[j] = z[node_id]

        # After getting all the nodes of a face assembled call the  cal. face area routine
        # face_area = calculate_face_area(face_x, face_y, face_z, "gaussian",
        # 4, coords_type)

        face_area = calculate_face_area(face_x, face_y, face_z, quadrature_rule,
                                        order, coords_type)

        area[i] = face_area

    return area


@njit
def calculate_spherical_triangle_jacobian(node1, node2, node3, dA, dB):
    """Calculate Jacobian of a spherical triangle. This is a helper function
    for calculating face area.

    Parameters
    ----------

    node1 : list, required
        First node of the triangle

    node1 : list, required
        Second node of the triangle

    node3 : list, required
        Third node of the triangle

    dA : double, required
        quadrature point

    dB : double, required
        quadrature point
    """
    dF = np.array([
        (1.0 - dB) * ((1.0 - dA) * node1[0] + dA * node2[0]) + dB * node3[0],
        (1.0 - dB) * ((1.0 - dA) * node1[1] + dA * node2[1]) + dB * node3[1],
        (1.0 - dB) * ((1.0 - dA) * node1[2] + dA * node2[2]) + dB * node3[2]
    ])

    dDaF = np.array([(1.0 - dB) * (node2[0] - node1[0]),
                     (1.0 - dB) * (node2[1] - node1[1]),
                     (1.0 - dB) * (node2[2] - node1[2])])

    dDbF = np.array([
        -(1.0 - dA) * node1[0] - dA * node2[0] + node3[0],
        -(1.0 - dA) * node1[1] - dA * node2[1] + node3[1],
        -(1.0 - dA) * node1[2] - dA * node2[2] + node3[2]
    ])

    dInvR = 1.0 / np.sqrt(dF[0] * dF[0] + dF[1] * dF[1] + dF[2] * dF[2])

    dDaG = np.array([
        dDaF[0] * (dF[1] * dF[1] + dF[2] * dF[2]) - dF[0] *
        (dDaF[1] * dF[1] + dDaF[2] * dF[2]),
        dDaF[1] * (dF[0] * dF[0] + dF[2] * dF[2]) - dF[1] *
        (dDaF[0] * dF[0] + dDaF[2] * dF[2]),
        dDaF[2] * (dF[0] * dF[0] + dF[1] * dF[1]) - dF[2] *
        (dDaF[0] * dF[0] + dDaF[1] * dF[1])
    ])

    dDbG = np.array([
        dDbF[0] * (dF[1] * dF[1] + dF[2] * dF[2]) - dF[0] *
        (dDbF[1] * dF[1] + dDbF[2] * dF[2]),
        dDbF[1] * (dF[0] * dF[0] + dF[2] * dF[2]) - dF[1] *
        (dDbF[0] * dF[0] + dDbF[2] * dF[2]),
        dDbF[2] * (dF[0] * dF[0] + dF[1] * dF[1]) - dF[2] *
        (dDbF[0] * dF[0] + dDbF[1] * dF[1])
    ])

    dDenomTerm = dInvR * dInvR * dInvR

    dDaG *= dDenomTerm
    dDbG *= dDenomTerm

    #  Cross product gives local Jacobian
    nodeCross = np.cross(dDaG, dDbG)
    dJacobian = np.sqrt(nodeCross[0] * nodeCross[0] +
                        nodeCross[1] * nodeCross[1] +
                        nodeCross[2] * nodeCross[2])

    return dJacobian


@njit
def calculate_spherical_triangle_jacobian_barycentric(node1, node2, node3, dA,
                                                      dB):
    """Calculate Jacobian of a spherical triangle. This is a helper function
    for calculating face area.

    Parameters
    ----------

    node1 : list, required
        First node of the triangle

    node1 : list, required
        Second node of the triangle

    node3 : list, required
        Third node of the triangle

    dA : double, required
        first component of barycentric coordinates of quadrature point

    dB : double, required
        second component of barycentric coordinates of quadrature point
    """

    dF = np.array([
        dA * node1[0] + dB * node2[0] + (1.0 - dA - dB) * node3[0],
        dA * node1[1] + dB * node2[1] + (1.0 - dA - dB) * node3[1],
        dA * node1[2] + dB * node2[2] + (1.0 - dA - dB) * node3[2]
    ])

    dDaF = np.array(
        [node1[0] - node3[0], node1[1] - node3[1], node1[2] - node3[2]])

    dDbF = np.array(
        [node2[0] - node3[0], node2[1] - node3[1], node2[2] - node3[2]])

    dInvR = 1.0 / np.sqrt(dF[0] * dF[0] + dF[1] * dF[1] + dF[2] * dF[2])

    dDaG = np.array([
        dDaF[0] * (dF[1] * dF[1] + dF[2] * dF[2]) - dF[0] *
        (dDaF[1] * dF[1] + dDaF[2] * dF[2]),
        dDaF[1] * (dF[0] * dF[0] + dF[2] * dF[2]) - dF[1] *
        (dDaF[0] * dF[0] + dDaF[2] * dF[2]),
        dDaF[2] * (dF[0] * dF[0] + dF[1] * dF[1]) - dF[2] *
        (dDaF[0] * dF[0] + dDaF[1] * dF[1])
    ])

    dDbG = np.array([
        dDbF[0] * (dF[1] * dF[1] + dF[2] * dF[2]) - dF[0] *
        (dDbF[1] * dF[1] + dDbF[2] * dF[2]),
        dDbF[1] * (dF[0] * dF[0] + dF[2] * dF[2]) - dF[1] *
        (dDbF[0] * dF[0] + dDbF[2] * dF[2]),
        dDbF[2] * (dF[0] * dF[0] + dF[1] * dF[1]) - dF[2] *
        (dDbF[0] * dF[0] + dDbF[1] * dF[1])
    ])

    dDenomTerm = dInvR * dInvR * dInvR

    dDaG *= dDenomTerm
    dDbG *= dDenomTerm

    #  Cross product gives local Jacobian
    nodeCross = np.cross(dDaG, dDbG)
    dJacobian = np.sqrt(nodeCross[0] * nodeCross[0] +
                        nodeCross[1] * nodeCross[1] +
                        nodeCross[2] * nodeCross[2])

    return 0.5 * dJacobian
