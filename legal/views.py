from django.shortcuts import render


def privacy_policy(request):
    return render(request, 'legal/privacy.html')


def terms_conditions(request):
    return render(request, 'legal/terms.html')