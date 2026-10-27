using System;
using MediaBrowser.Controller.Net;
using MediaBrowser.Model.Services;

namespace Emby.SubtitleAssistant.Web;

public static class AdminAccess
{
    public static bool IsAdministrator(AuthorizationInfo authorization) => authorization?.User?.Policy?.IsAdministrator == true;

    internal static void Require(IAuthorizationContext authorization, IRequest request)
    {
        if (request == null || !IsAdministrator(authorization.GetAuthorizationInfo(request)))
            throw new SecurityException("Administrator access required.");
    }
}
